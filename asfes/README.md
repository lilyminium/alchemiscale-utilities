## How to run some ASFE simulations with OpenFE and Pontibus on Alchemiscale.

This is a test run of Pontibus

### 1. Create an AlchemicalNetwork

First you need to create a :class:`AlchemicalNetwork` which defines all the transformations
you want to run. In this case, each transformation is an absolute hydration free energy using
OpenFE's :class:`AbsoluteSolvationProtocol`. This is done in the `create_network.py` script.

Here we take a list of smiles as input (see :meth:`get_smiles`). We then convert them to
OpenFF Molecules and charge them with EFL10 (see :meth:`gen_off_molecule`).

We then assign a set of simulation settings for the Protocol (see :meth:`get_settings`)
to create each Transformation in the :class:`AlchemicalNetwork` (see :meth:`get_alchem_network`).

The Transformations are defined as a change in ChemicalSystem going from a SmallMoleculeComponent
with a SolventComponent (stateA) to only a SolventComponent (stateB).

Here is an example call for the script:

```bash
python create_network.py --input_filename inputs.dat --network_filename network.json
```

### 2. Submit the AlchemicalNetwork

Next we submit the :class:`AlchemicalNetwork` to Alchemiscale and action out the tasks.

#### Setting your Alchemiscale user id / key

To submit to Alchemiscale, you must have either a user ID or key.

Here we expect your id/key to either be set as the environment variables `ALCHEMISCALE_ID`
and `ALCHEMISCALE_KEY` or to be passed via the ``--user_id`` and ``--user_key`` flags.

#### Setting your Scope

Every experiment needs a Scope to keep track of what you are doing.

The scope is defined in three parts: `<organization>`, `<campaign>`, `<project>`.

For benchmarking, we often set the campaign to be an indicator of a given stack version,
and the project to be the experiment, i.e. `<openfe>`, `<openfe_v1.2>`, `<minisolv_elf10>`.

Remember that you are not allowed certain types of characters in your scope, such as; `-`.

You can read more about the scope here: https://docs.alchemiscale.org/en/latest/user_guide.html#choosing-a-scope

#### Setting the number of repeats

On Alchemiscale we set each task to run a single DAG of a Protocol. However we can
have multiple repeats (in order to get better estimates of the sampling error) by
submitting the same task multiple times.

To do this, we can use the ``--repeats`` flag.


#### Example

Here is an example call for the script w/ 3 repeats per Transformation on the openfe scope:

```bash
python submit.py --network_filename network.json --org_scope "openff" --scope_name_campaign "test_afes" --scope_name_project "test_asfes_small" --repeats 3 --user_id $ALCHEMISCALE_ID --user_key $ALCHEMISCALE_KEY
```

### 3. Monitoring your simulation

You can monitor your simulation by querying the Alchemiscale network status.

To help with this, we provide the ``monitor.py` script.

You can call it like this:

```bash
python monitor.py --scope_key scoped-key.dat
```

Here ``scoped-key.dat`` is the serialized ScopedKey that we generated when we
called ``submit.py``.

As per the ``submit.py`` script, you can also manually pass your user ID/key.

#### Restarting simulations

In some cases you might find that some jobs have failed and gone to ``error`` mode.
Due to the heterogenous nature of Alchemiscale, this can often happen due to hardware
failures or other random issues. It is usually advised to try to restart the simulations
a few times to see what happens.

You can use the ``--restart`` flag to achieve this:

```bash
python monitor.py --scope_key scoped-key.dat --restart
```

This will put all errored tasks back into the queue and attempt to run them again.


### 4. Getting results.

Finally, once your simulations are complete, you can gather the free energy results.

This can be done with ``gather.py`` in the following manner:

```bash
python gather.py --scope_key scoped-key.dat --output_file results.dat
```

This scripts scans through all the Transformations and gathers ProtocolDAGResults.
It then takes the dG estimates for all the repeats and returns an average and a standard deviation.

Note 1: if you only run a single repeat, it may be useful to directly use the MBAR error. This
is not done here, but this script could be easily modified to do this.

Note 2: the ProtocolDAGResults contain other types of information, such as the MBAR overlap matrix
and the forward & reverse energy series. Again, this data is not obtained with this script but
it could be modified to retrieve this.
