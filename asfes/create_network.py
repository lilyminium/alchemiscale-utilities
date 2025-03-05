import click
import itertools
import openfe
import gufe
from gufe import tokenization
import pathlib
from openff.toolkit import Molecule
from openff.toolkit.utils.toolkits import OpenEyeToolkitWrapper
from openff.units import unit
import openfe
from openfe import SmallMoleculeComponent
from openfe.protocols.openmm_afe import AbsoluteSolvationProtocol
from openfe.utils import without_oechem_backend
import numpy as np
import json


from pontibus.components.extended_solvent_component import ExtendedSolventComponent
from pontibus.protocols.solvation import ASFEProtocol
from pontibus.protocols.solvation.settings import PackmolSolvationSettings

def get_smiles(filename: pathlib.Path) -> list[str]:
    """
    Get a list of smiles from an input file.

    Parameters
    ----------
    filename : pathlib.Path
      The file to read smiles from.

    Returns
    -------
    data : list[str]
      A list of smiles strings
    """
    # get a list of smiles
    with open(filename, 'r') as f:
        data = f.read().splitlines()
    return data


def gen_off_molecule(smi: str) -> Molecule:
    """
    Generate an openff molecule from an input smiles

    Parameters
    ----------
    smi : str
      A smiles string

    Returns
    -------
    m : Molecule
      An OpenFF Molecule.
    """
    m = Molecule.from_smiles(smi)
    m.generate_conformers()
    m.assign_partial_charges(
        'am1bccelf10',
        use_conformers=m.conformers,
        toolkit_registry=OpenEyeToolkitWrapper(),
    )
    m.name = smi
    return m


def get_settings():
    """
    Return some settings for the ASFEProtocol
    """
    settings = ASFEProtocol.default_settings()
    # Always set the repeats to 1 for alchemiscale
    settings.protocol_repeats = 1

    # Thermodynamic settings
    settings.thermo_settings.temperature = 298.15 * unit.kelvin
    settings.thermo_settings.pressure = 1 * unit.bar

    # Force field settings
    settings.solvent_forcefield_settings.forcefields = ["openff-2.2.1.offxml"]
    settings.solvent_forcefield_settings.hydrogen_mass = 1.00784
    settings.vacuum_forcefield_settings.forcefields = ["openff-2.2.1.offxml"]
    settings.vacuum_forcefield_settings.hydrogen_mass = 1.00784
    
    # Solvation settings
    # must be None for number of mols
    settings.solvation_settings = PackmolSolvationSettings(
        number_of_solvent_molecules=1000,
        solvent_padding=None
    )

    # Integrator settings
    settings.integrator_settings.timestep = 2 * unit.femtosecond
    settings.integrator_settings.barostat_frequency = 25 * unit.timestep

    # Non-alchemical Equilibration settings (you do this first)

    # note -- defaults in protocol are:
    # solvent: 0.5 ns NVT, 0.5 ns NPT, 9.5 ns production
    # vacuum: No NVT, 0.2 ns NPT, 0.5 ns production
    settings.solvent_equil_simulation_settings.equilibration_length_nvt = 100 * unit.picosecond
    settings.solvent_equil_simulation_settings.equilibration_length = 100 * unit.picosecond
    settings.solvent_equil_simulation_settings.production_length = 100 * unit.picosecond
    settings.vacuum_equil_simulation_settings.equilibration_length_nvt = 0 * unit.picosecond # Vacuum != NVT
    settings.vacuum_equil_simulation_settings.equilibration_length = 100 * unit.picosecond
    settings.vacuum_equil_simulation_settings.production_length = 100 * unit.picosecond

    # Alchemical Equilibration settings (then you run this)
    # defaults are:
    # solvent: 1 ns equilibration, 10 ns production
    # vacuum: 0.5 ns equilibration, 2 ns production
    settings.solvent_simulation_settings.equilibration_length = 200 * unit.picosecond
    settings.vacuum_simulation_settings.equilibration_length = 200 * unit.picosecond
    # Alchemical Production settings (then you sample from this)
    settings.solvent_simulation_settings.production_length = 2000 * unit.picosecond
    settings.vacuum_simulation_settings.production_length = 2000 * unit.picosecond
    # Set the exchange rates
    settings.solvent_simulation_settings.time_per_iteration = 1 * unit.picosecond
    settings.vacuum_simulation_settings.time_per_iteration = 1 * unit.picosecond
    # Set the lambda schedule (note these are reversed from what evaluator does!)
    settings.lambda_settings.lambda_elec = [
        0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0,
        1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0
    ]
    settings.lambda_settings.lambda_vdw = [
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35,
        0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0
    ]
    settings.lambda_settings.lambda_restraints = [
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    ]
    # Set the number of replicas
    settings.vacuum_simulation_settings.n_replicas = 26
    settings.solvent_simulation_settings.n_replicas = 26
    return settings


def _get_stateB(
    solvent_component: openfe.SolventComponent
) -> openfe.ChemicalSystem:
    """
    Return a ChemicalSystem for stateB which only contains
    the input SolventComponent

    Parameters
    ----------
    solvent_component : openfe.SolventComponent
      A SolventComponent defining how the system will be solvated.

    Returns
    -------
    openfe.ChemicalSystem
      A ChemicalSystem containing only the SolventComponent
    """
    return openfe.ChemicalSystem({'solvent': solvent_component})


def _get_stateA(
    small_molecule_component,
    solvent_component
) -> openfe.ChemicalSystem:
    """
    Get a ChemicalSystem for stateA containing the small molecule
    and the solvent_component

    Parameters
    ----------
    small_molecule_component : openfe.SmallMoleculeComponent
      The small molecule to alchemically transform.
    solvent_component : openfe.SolventComponent
      A SolventComponent defining how the system will be solvated.

    Returns
    -------
    openfe.ChemicalSystem
      A ChemicalSystem for stateA.
    """
    return openfe.ChemicalSystem(
        {'ligand': small_molecule_component, 'solvent': solvent_component}
    )


def get_small_molecule_components(
    filename: str
) -> list[SmallMoleculeComponent]:
    """
    Get a list of SmallMoleculeComponents

    Parameters
    ----------
    filename : str
      A string to the filename with the smiles.

    Returns
    -------
    smcs : list[SmallMoleculeComponent]
      A list of SmallMoleculeComponent for each ligand
      in the input smiles.

    What this does:
    ---------------
    * Loop through the input list of smiles.
    * Generate an OpenFF molecule for each entry
    * Turn the molecule into an openfe SmallMolculeComponent (smc)
    * Return a list of the smcs)
    """
    smiles = get_smiles(filename)

    smcs = []

    for smi in smiles:
        offmol = gen_off_molecule(smi)
        comp = SmallMoleculeComponent.from_openff(offmol, name=offmol.name)
        smcs.append(comp)

    return smcs


def get_alchem_network(
    input_filename,
    protocol,
    ion_concentration: unit.Quantity = 0.0*unit.molar
) -> openfe.AlchemicalNetwork:
    """
    Create a transformation network from all the input ligands.

    Parameters
    ----------
    smcs : list[openfe.SmallMoleculeComponent]
      A list of SmallMoleculeComponents for which an AHFE will
      be calculated.
    solvents : list[openfe.SolventComponent]
      A list of SolventComponents defining the solvent phase.
    protocol : AbsoluteSolvationProtocol
      An AbsoluteSolvationProtocol object defining the Transformation Protocol.
    """
    solutes = get_small_molecule_components(input_filename)

    # get pair combinations of smiles
    transformations = []

    for solute, solvent_smc in itertools.permutations(solutes, 2):
        solvent = ExtendedSolventComponent(
            solvent_molecule=solvent_smc,
            ion_concentration=ion_concentration
          )
        stateA = _get_stateA(solute, solvent)
        stateB = _get_stateB(solvent)

        t = openfe.Transformation(
            stateA=stateA, stateB=stateB,
            mapping=None,
            protocol=protocol,
            name=solute.name
        )
        transformations.append(t)

    return openfe.AlchemicalNetwork(transformations)

@click.command
@click.option(
    '--input_filename',
    type=click.Path(dir_okay=False, file_okay=True, path_type=pathlib.Path),
    required=True,
    help="Path to the input file of smiles",
)
@click.option(
    '--network_filename',
    type=click.Path(dir_okay=False, file_okay=True, path_type=pathlib.Path),
    required=True,
    help="File location where the Alchemical Network should be written to",
)
def run(input_filename, network_filename):
    """
    Create an AlchemicalNetwork of AHFE transformations for each
    molecule in a list of smiles.

    Parameters
    ----------
    input_filename : pathlib.Path
      A path to an input file with a list of smiles.
    network_filename : pathlib.Path
      A path to the file where the AlchemicalNetwork will be written.
    """

    # Simulation settings
    settings = get_settings()

    # Create a Protocol object
    protocol = ASFEProtocol(settings=settings)

    # Create an Alchemical Network
    network = get_alchem_network(input_filename, protocol)

    # Write out the alchemical network
    with open(network_filename, 'w') as f:
        json.dump(
            network.to_dict(),
            f,
            cls=tokenization.JSON_HANDLER.encoder
        )


if __name__ == "__main__":
    run()

