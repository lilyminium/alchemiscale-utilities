import click
import os
import pathlib
import numpy as np
from openff.units import unit
import pathlib
from typing import Optional
from alchemiscale import AlchemiscaleClient, Scope, ScopedKey


def _get_average_and_stdevs(estimates) -> tuple[unit.Quantity, unit.Quantity]:
    """
    Get the average and stdev from a series
    of estimates.

    Parameters
    ----------
    estimates : list[unit.Quantity]
      A list of dG estimates for each repeat.

    Returns
    -------
    avg : unit.Quantity
      The average dG value.
    stdev : unit.Quantity
      The standard deviation of all estimates.
    """
    u = estimates[0].u
    dGs = [i.to(u).m for i in estimates]

    avg = np.average(dGs) * u
    stdev = np.std(dGs) * u

    return avg, stdev


def _process_dagresults(
    dag_results
) -> tuple[Optional[unit.Quantity], Optional[unit.Quantity]]:
    """
    Process a list of ProtocolDAGResults and get the average dG and error.

    If the list is empty, returns ``None, None``.

    Parameters
    ----------
    dag_results : list[ProtocolDAGResult]
      A list of ProtocolDAGResult for a transformation.

    Returns
    -------
    dG : Optional[unit.Quantity]
      The average free energy for a transformation.
    err : Optional[unit.Quantity]
      The standard deviation in the free energy estimate between multiple
      repeats.
    """

    if len(dag_results) == 0:
        return None, None

    dG = {'solvent': [], 'vacuum': []}

    for dresult in dag_results:
        for result in dresult.protocol_unit_results:
            if result.ok():
                dG[result.outputs['simtype']].append(
                    result.outputs['unit_estimate']
                )

    vac_dG, vac_err = _get_average_and_stdevs(dG['vacuum'])
    sol_dG, sol_err = _get_average_and_stdevs(dG['solvent'])

    dG = vac_dG - sol_dG
    err = np.sqrt(vac_err**2 + sol_err**2)

    return dG, err


def _write_results(results, results_file) -> None:
    """
    Write out a tab separate list of results for each transformation.

    If the transformation results are not present, writes ``None``.

    Parameters
    ----------
    results : dict[str, list[unit.Quantity]]
      A dictionary keyed by transformation names with each entry
      containing a list of dG and stdev values for each transformation.
    results_file : pathlib.Path
      A path to the file where the results will be written.
    """
    with open(results_file, 'w') as f:
        f.write("molecule\tdG (kcal/mol)\tstdev (kcal/mol)\n")
        for r in results.keys():
            if results[r][0] is None:
                f.write(f"{r}\tNone\tNone\n")
            else:
                f.write(f"{r}\t{results[r][0].m}\t{results[r][1].m}\n")


@click.command
@click.option(
    '--scope_key',
    type=click.Path(dir_okay=False, file_okay=True, path_type=pathlib.Path),
    required=True,
    default="scoped-key.dat",
    help="Path to a serialized ScopedKey",
)
@click.option(
    '--output_file',
    type=click.Path(dir_okay=False, file_okay=True, path_type=pathlib.Path),
    required=True,
    default="results.dat",
    help="File location where the results TSV will be written.",
)
@click.option(
    '--user_id',
    type=str,
    required=False,
    default=None,
)
@click.option(
    '--user_key',
    type=str,
    required=False,
    default=None,
)
def run(
    scope_key: pathlib.Path,
    output_file: pathlib.Path,
    user_id: Optional[str],
    user_key: Optional[str],
):
    """
    Gather transformation results.

    Parameters
    ----------
    scope_key : pathlib.Path
      A path to a serialized ScopeKey
    user_id : Optional[str]
      A string for a user ID, if undefined will
      fetch from the environment variable ALCHEMISCALE_ID.
    user_key: Optional[str]
      A string for the user key, if underfined will
      fetch from the environment variable ALCHEMISCALE_KEY.
    """
    # Get the alchemiscale bits
    if user_id is None:
        user_id = os.environ['ALCHEMISCALE_ID']
    if user_key is None:
        user_key = os.environ['ALCHEMISCALE_KEY']
    asc = AlchemiscaleClient(
        'https://api.alchemiscale.org',
        user_id,
        user_key
    )


    # Read in the ScopeKey
    with open(scope_key, 'r') as f:
        network_sk = f.read()

    # Loop through each transformation and get the results

    results = {}  # The results container
    for transf_sk in asc.get_network_transformations(network_sk):
        transf = asc.get_transformation(transf_sk)
        dag_results = asc.get_transformation_results(
            transf_sk, return_protocoldagresults=True,
        )

        dG, err = _process_dagresults(dag_results)

        results[transf.name] = (dG, err)

    # Write out all the results
    _write_results(results, output_file)


if __name__ == "__main__":
    run()

