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
@click.option('--name-prefix', default='')
@click.option('--output-dir', default='.')
def main(
    optimization_info_path: str,
    execution_info_path: str,
    name_prefix: str,
    output_dir: str,
):
    optimization_info = json.loads(Path(optimization_info_path).read_text())
    execution_info = json.loads(Path(execution_info_path).read_text())

    optimization_table = DataFrame(optimization_info)
    optimization_table.set_index(['index'], inplace=True)

    execution_table = DataFrame(execution_info)
    execution_table['index'] = [split_bin_file_name(file_name)['index'] for file_name in execution_table['file']]
    execution_table.set_index(['index'], inplace=True)

    step_table = DataFrame({
        'step': STEP_NAMES.keys(),
        'step_name': STEP_NAMES.values(),
    })
    step_table.set_index(['step'], inplace=True)

    merged_table = pandas.merge(optimization_table, execution_table, on='index', how='outer')
    unknown_steps = set(merged_table['step'].unique()) - set(step_table.index) - {None}
    require(len(unknown_steps) == 0, f"Unknown steps in the sequence: {unknown_steps}")
    merged_table = pandas.merge(merged_table, step_table, left_on='step', right_index=True, how='inner').sort_index()

    selected_columns = ['step', 'step_name', 'bytecode_size', 'creation_gas', 'runtime_gas']
    pretty_table = merged_table[selected_columns]

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    pretty_table.to_json(Path(output_dir) / f'{name_prefix}report.json', orient='columns', indent=4)


if __name__ == '__main__':
    main()
