#!/usr/bin/env python3

import json
from pathlib import Path

import click
import matplotlib.pyplot as plt
import numpy
from pandas import DataFrame
import pandas
from tabulate import tabulate

import seqbench_helpers
from seqbench_helpers import fail
from seqbench_helpers import format_percent
from seqbench_helpers import require


def plot_column_with_step_labels(table: DataFrame, column_name: str, ylabel: str, title: str, style: str = 'line', origin_at_zero: bool = True):
    assert style in {'line', 'bar'}

    if style == 'bar':
        axes = table[column_name].plot.bar(title=title, xlabel='step', ylabel=ylabel, figsize=(25, 15))
        axes.grid(axis='y')
        plt.tick_params(bottom=False, labelbottom=False)
    else:
        axes = table[column_name].plot(title=title, xlabel='step', ylabel=ylabel, figsize=(25, 15), grid=True)
        axes.ticklabel_format(useOffset=False, style='plain')
    if origin_at_zero:
        axes.set_ylim(bottom=0)
        axes.set_xlim(left=0)
    for index, step, value in zip(table.index, table['step'], table[column_name]):
        axes.annotate(step, (index, value), xytext=(0, 5), textcoords='offset points', size=7)


def plot_xy_with_step_labels(table: DataFrame, x_column: str, y_column: str, xlabel: str, ylabel: str, title: str, start_index: int = 0, origin_at_zero: bool = True):
    x_values = table[x_column][start_index:]
    y_values = table[[y_column]][start_index:].set_index(x_values)
    axes = y_values.plot(title=title, xlabel=xlabel, ylabel=ylabel, figsize=(25, 15), grid=True, ax=plt.gca())
    axes.ticklabel_format(useOffset=False, style='plain')
    if origin_at_zero:
        axes.set_ylim(bottom=0)
        axes.set_xlim(left=0)
    for step, x, y in zip(table['step'][start_index:], x_values, y_values[y_column]):
        axes.annotate(step, (x, y), xytext=(0, 5), textcoords='offset points', size=7)


def format_table(table: DataFrame, int_format_bug_workaround: bool = False) -> str:
    # Allow column names with dashes to wrap to keep columns narrower
    table = table.rename(columns={name: name.replace('_', ' ') for name in table.columns})

    # astype('object') allows us to put the empty string even in columns that enforce a non-string dtype
    prepared_table = table.astype('object').fillna('')
    show_index = True

    if int_format_bug_workaround:
        # FIXME: When the table contains no columns with dtype 'object', tabulate seems to treat 'int' columns as 'float'.
        # This happens even when there are only 'int' columns in the table.
        # Probably also related to https://github.com/astanin/python-tabulate/issues/18.
        # As a workaround, manually flatten the table before printing.
        prepared_table = [
            {prepared_table.index.name: index} | row
            for index, row in zip(prepared_table.index, prepared_table.to_dict('records'))
        ]
        show_index = False

    return tabulate(prepared_table, headers='keys', tablefmt='pipe', showindex=show_index, intfmt=',')


def build_comparison_table(column_name: str, tables: list[DataFrame], table_names: list[str], shared_step_column: bool) -> DataFrame:
    assert len(tables) > 0
    assert len(tables) == len(table_names)

    if shared_step_column:
        comparison_table = tables[0][['step', 'step_name']]
    else:
        comparison_table = pandas.DataFrame(index=tables[0].index)

    for table, table_name in zip(tables, table_names):
        if not shared_step_column:
            comparison_table[f'step {table_name}'] = table['step']

        comparison_table = comparison_table.merge(
            table[[column_name]].rename(columns={column_name: table_name}),
            left_index=True,
            right_index=True,
            how='outer'
        )

    return comparison_table


def build_summary_table(selected_columns: list[str], tables: list[DataFrame], report_names: list[str], value_set: str) -> DataFrame:
    assert len(tables) == len(report_names)
    assert all(len(table) > 0 for table in tables)
    assert all('' not in table for table in tables)
    assert value_set in ['before', 'after', 'min']

    def summary_row(table, report_name, value_set):
        if value_set == 'before':
            row = table.iloc[[0]].reset_index(drop=True)
        elif value_set == 'after':
            row = table.iloc[[-1]].reset_index(drop=True)
        elif value_set == 'min':
            row = table.min(numeric_only=True).to_frame().T

        row[''] = report_name
        return row.set_index('')

    return pandas.concat([
        summary_row(table[selected_columns], report_name, value_set)
        for table, report_name in zip(tables, report_names)
    ])


def simplify_report_names(report_names: list[str]):
    assert len(report_names) == len(set(report_names))

    def prefix(name):
        return name.split('/', 1)[0]

    report_name_prefixes = [prefix(name) for name in report_names]
    return [prefix(name) if report_name_prefixes.count(prefix(name)) <= 1 else name for name in report_names]


@click.command()
@click.argument('report_paths', nargs=-1)
@click.option('--report-name', multiple=True, default=[''])
@click.option('--show-table', is_flag=True, default=False)
@click.option('--show-plot', is_flag=True, default=False)
@click.option('--name-prefix', default='')
@click.option('--output-dir', default='.')
@click.option('--document-title', default=None)
def main(
    report_paths: tuple[str],
    report_name: tuple[str],
    show_table: bool,
    show_plot: bool,
    name_prefix: str,
    output_dir: str,
    document_title: str | None,
):
    tables = [pandas.read_json(path) for path in report_paths]
    if len(tables) == 0:
        print("No input files specified.")
        return

    for table in tables:
        # NOTE: If there is even one float column, python-tabulate converts all int columns to float as well.
        # The fix is available but not in the latest release yet, see: https://github.com/astanin/python-tabulate/issues/18.
        # Just convert time columns to microseconds, both to avoid this and for consistency.
        table['compilation_time'] = (table['compilation_time'] * 10**6).round().astype({'compilation_time': int})
        table.rename(columns={'duration_microsec': 'duration'}, inplace=True)

    require(len(report_name) == len(set(report_name)), "Report names are not unique.")
    require(len(report_name) == len(report_paths), "The number of reports does not match the number of report names given.")
    require(all(name.count('/') <= 1 for name in report_name), "Report name can contain at most one slash.")

    simple_report_names = simplify_report_names(report_name)

    tables_have_compatible_steps = True
    for i, other_table in enumerate(tables[1:]):
        shared_indices = tables[0].index.intersection(other_table.index)
        if (tables[0]['step'].loc[shared_indices] != other_table['step'].loc[shared_indices]).any():
            tables_have_compatible_steps = False
            break
        require(
            (tables[0]['step_name'].loc[shared_indices] == other_table['step_name'].loc[shared_indices]).all(),
            f"Tables 0 and {i + 1} use different names for some of the same steps.",
        )

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    selected_columns = [
        'runtime_gas',
        'bytecode_size',
        'creation_gas',
        'duration',
        'optimization_time',
        'compilation_time',
    ]
    assert 'step' not in selected_columns
    assert 'step_name' not in selected_columns

    document = f"## {document_title}\n\n" if document_title is not None else ''

    summary_columns = [c for c in selected_columns if c != 'duration']

    document += f"\n\n### Summary\n\n"

    def add_summary_table(title, summary_table):
        nonlocal document
        formatted_table = format_table(summary_table, int_format_bug_workaround=True)
        if show_table:
            print(formatted_table)
        document += f"#### {title}\n\n{formatted_table}\n\n"

    minimized_columns = [
        'runtime_gas',
        'bytecode_size',
        'creation_gas',
    ]
    assert set(minimized_columns).issubset(set(selected_columns))

    before_summary_table = build_summary_table(summary_columns, tables, simple_report_names, 'before')
    after_summary_table  = build_summary_table(summary_columns, tables, simple_report_names, 'after')
    min_summary_table    = build_summary_table(summary_columns, tables, simple_report_names, 'min')
    add_summary_table("Final values", after_summary_table)

    diff_table = (
        (after_summary_table[minimized_columns] - before_summary_table[minimized_columns]) /
        before_summary_table[minimized_columns]
    ).fillna(numpy.nan).replace([numpy.nan], [None]).applymap(format_percent)
    min_diff_table = (
        (min_summary_table[minimized_columns] - before_summary_table[minimized_columns]) /
        before_summary_table[minimized_columns]
    ).fillna(numpy.nan).replace([numpy.nan], [None]).applymap(format_percent)

    combined_diff_table = diff_table.where(
        diff_table == min_diff_table,
        diff_table + ' (_min: ' + min_diff_table + '_)',
    )
    add_summary_table("Final values vs unoptimized", combined_diff_table)

    document += f"\n\n### Plots\n\n"

    def add_plot_vs_index(plot_name, column, ylabel, title, style='line'):
        nonlocal document
        plt.figure(title)
        for table in tables:
            plot_column_with_step_labels(table, column, ylabel, title, style, origin_at_zero=(len(tables) == 1))
        plt.legend(simple_report_names)
        plot_file_name = f'{name_prefix}{plot_name}.svg'
        plt.savefig(Path(output_dir) / plot_file_name)
        document += f"#### {title}\n\n![{title}]({plot_file_name})\n"

    def add_plot_vs_time(plot_name, y_column, ylabel, title):
        nonlocal document
        plt.figure(title)
        for table in tables:
            plot_xy_with_step_labels(
                table,
                'optimization_time',
                y_column,
                'time (microseconds)',
                ylabel,
                title,
                start_index=1,
                origin_at_zero=(len(tables) == 1),
            )
        plt.legend(simple_report_names)
        plot_file_name = f'{name_prefix}{plot_name}.svg'
        plt.savefig(Path(output_dir) / plot_file_name)
        document += f"#### {title}\n\n![{title}]({plot_file_name})\n"

    add_plot_vs_index('runtime-gas', 'runtime_gas', 'gas', 'Test execution cost after each step')
    if 'optimization_time' in tables[0].columns:
        add_plot_vs_time('runtime-gas-vs-optimization-time', 'runtime_gas', 'gas', 'Test execution cost vs optimization time')

    add_plot_vs_index('bytecode-size', 'bytecode_size', 'size (bytes)', 'Bytecode size after each step')
    if 'optimization_time' in tables[0].columns:
        add_plot_vs_time('bytecode-size-vs-optimization-time', 'bytecode_size', 'size (bytes)', 'Bytecode size vs optimization time')

    add_plot_vs_index('creation-gas', 'creation_gas', 'gas', 'Contract deployment cost after each step')
    if 'optimization_time' in tables[0].columns:
        add_plot_vs_time('creation-gas-vs-optimization-time', 'creation_gas', 'gas', 'Contract deployment cost vs optimization time')

    if 'optimization_time' in tables[0].columns and 'duration' in tables[0].columns:
        duration_plot_style = 'bar' if len(tables) == 1 else 'line'
        add_plot_vs_index('step-duration', 'duration', 'time (microseconds)', 'Duration of each step', style=duration_plot_style)
        add_plot_vs_index('optimization-time', 'optimization_time', 'time (microseconds)', 'Cumulative optimization time after each step')

    add_plot_vs_index('compilation-time', 'compilation_time', 'time (microseconds)', 'Compilation time with a prefix ending at this step')

    document += f"\n\n### Tables\n\n"

    if len(tables) == 1:
        formatted_table = format_table(tables[0][['step', 'step_name'] + selected_columns])
        if show_table:
            print(formatted_table)
        if simple_report_names[0] != '':
            document += f"#### {simple_report_names[0]}\n\n"
        document += formatted_table + '\n\n'
    else:
        for column in selected_columns:
            if column in tables[0].columns:
                document += f"#### {column}\n\n"
                formatted_table = format_table(build_comparison_table(column, tables, simple_report_names, shared_step_column=tables_have_compatible_steps))
                if show_table:
                    print(f"\n{column}\n")
                    print(formatted_table)
                document += formatted_table + '\n\n'

    if show_plot:
        plt.show()

    with open(Path(output_dir) / f'{name_prefix}report.md', 'w') as document_file:
        document_file.write(document)


if __name__ == '__main__':
    main()
