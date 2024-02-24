#!/usr/bin/env python3
import json
from pathlib import Path
import re

import click
from pandas import DataFrame
import pandas


BIN_FILE_NAME_REGEX = re.compile(r'(.*)-step-(\d{5})(?:-([a-zA-Z]))?.bin')

STEP_NAMES = {
    'a': 'SSATransform',
    'C': 'ConditionalSimplifier',
    'c': 'CommonSubexpressionEliminator',
    'D': 'DeadCodeEliminator',
    'd': 'VarDeclInitializer',
    'E': 'EqualStoreEliminator',
    'e': 'ExpressionInliner',
    'F': 'FunctionSpecializer',
    'f': 'BlockFlattener',
    'g': 'FunctionGrouper',
    'h': 'FunctionHoister',
    'I': 'ForLoopConditionIntoBody',
    'i': 'FullInliner',
    'j': 'ExpressionJoiner',
    'L': 'LoadResolver',
    'l': 'CircularReferencesPruner',
    'M': 'LoopInvariantCodeMotion',
    'm': 'Rematerialiser',
    'n': 'ControlFlowSimplifier',
    'O': 'ForLoopConditionOutOfBody',
    'o': 'ForLoopInitRewriter',
    'p': 'UnusedFunctionParameterPruner',
    'r': 'UnusedAssignEliminator',
    'S': 'UnusedStoreEliminator',
    's': 'ExpressionSimplifier',
    'T': 'LiteralRematerialiser',
    't': 'StructuralSimplifier',
    'U': 'ConditionalUnsimplifier',
    'u': 'UnusedPruner',
    'V': 'SSAReverser',
    'v': 'EquivalentFunctionCombiner',
    'x': 'ExpressionSplitter',
}


def fail(message: str | None = None):
    raise click.ClickException(click.style(message if message is not None else "Validation failed.", fg='red'))


def require(condition: bool, message: str | None = None):
    if not condition:
        fail(message)


def split_bin_file_name(file_name: str) -> dict:
    match = re.match(BIN_FILE_NAME_REGEX, file_name)
    assert match is not None
    return {
        'contract': match[1],
        'index': int(match[2]),
        'step': match[3],
    }


@click.command()
@click.argument('optimization_info_path', nargs=1)
@click.argument('execution_info_path', nargs=1)
@click.argument('sequence_info_path', required=False, nargs=1)
@click.option('--name-prefix', default='')
@click.option('--output-dir', default='.')
def main(
    optimization_info_path: str,
    execution_info_path: str,
    sequence_info_path: str | None,
    name_prefix: str,
    output_dir: str,
):
    optimization_info = json.loads(Path(optimization_info_path).read_text())
    execution_info = json.loads(Path(execution_info_path).read_text())
    if sequence_info_path is not None:
        sequence_info = json.loads(Path(sequence_info_path).read_text())
        sequence_info = sequence_info[0]['steps']

    optimization_table = DataFrame(optimization_info)
    optimization_table.set_index(['index'], inplace=True)

    execution_table = DataFrame(execution_info)
    execution_table['index'] = [split_bin_file_name(file_name)['index'] for file_name in execution_table['file']]
    execution_table.set_index(['index'], inplace=True)

    if sequence_info_path is not None:
        sequence_table = DataFrame(sequence_info)
        sequence_table = sequence_table[sequence_table.hardcoded == False]
        sequence_table.set_index(['index'], inplace=True)
        sequence_table.reset_index(inplace=True)
        sequence_table.index += 1
        # NOTE: Execution info may be missing info for some steps if compilation or execution failed
        require((execution_table.index[1:].isin(sequence_table.index)).all(), "Step indexes in sequence info do not match execution info.")

    step_table = DataFrame({
        'step': STEP_NAMES.keys(),
        'step_name': STEP_NAMES.values(),
    })
    step_table.set_index(['step'], inplace=True)

    merged_table = pandas.merge(optimization_table, execution_table, on='index', how='outer')
    if sequence_info_path is not None:
        require((
            (optimization_table['step'][1:] == sequence_table['step']) |
            optimization_table['step'][1:].isna()
        ).all(), "Steps in sequence info do not match optimization info.")
        merged_table = pandas.merge(
            merged_table,
            # Step columns are identical except for index 0, where sequence_table is missing an item. Not dropping the column
            # would result in two separate columns after merge (step_x and step_y).
            sequence_table.drop(columns=['step']),
            left_on='index',
            right_index=True,
            how='outer',
        )

    unknown_steps = set(merged_table['step'].unique()) - set(step_table.index) - {None}
    require(len(unknown_steps) == 0, f"Unknown steps in the sequence: {unknown_steps}")
    merged_table = pandas.merge(merged_table, step_table, left_on='step', right_index=True, how='inner').sort_index()

    selected_columns = ['step', 'step_name', 'bytecode_size', 'creation_gas', 'runtime_gas', 'compilation_time']
    if sequence_info_path is not None:
        selected_columns += ['duration_microsec', 'optimization_time']
        # Replace empty values with 0 because they force column type to float.
        # There should be only one empty value anyway (at index 0, i.e. before the first step)
        merged_table['duration_microsec'].fillna(0, inplace=True)
        merged_table['optimization_time'] = merged_table['duration_microsec'].cumsum()

    pretty_table = merged_table[selected_columns]

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    pretty_table.to_json(Path(output_dir) / f'{name_prefix}report.json', orient='columns', indent=4)


if __name__ == '__main__':
    main()
