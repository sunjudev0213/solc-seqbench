#!/usr/bin/env python3

import json
from pathlib import Path

import click
import matplotlib.pyplot as plt
from pandas import DataFrame
import pandas
from tabulate import tabulate


def plot_column_with_step_labels(table: DataFrame, column_name: str, ylabel: str, title: str):
    plt.figure(title)
    axes = table[column_name].plot(title=title, xlabel='step', ylabel=ylabel, figsize=(25, 15), grid=True)
    axes.ticklabel_format(useOffset=False, style='plain')
    axes.set_ylim(bottom=0)
    axes.set_xlim(left=0)
    for index, step, value in zip(table.index, table['step'], table[column_name]):
        axes.annotate(step, (index, value), xytext=(0, 5), textcoords='offset points', size=7)


def format_table(table: DataFrame) -> str:
    return tabulate(
        # astype('object') allows us to put the empty string even in columns that enforce a non-string dtype
        table.astype('object').fillna(''),
        headers='keys',
        tablefmt='github',
        showindex=True,
    )


@click.command()
@click.argument('report_path', nargs=1)
@click.option('--show-table', is_flag=True, default=False)
@click.option('--show-plot', is_flag=True, default=False)
@click.option('--name-prefix', default='')
@click.option('--output-dir', default='.')
@click.option('--document-title', default=None)
def main(
    report_path: str,
    show_table: bool,
    show_plot: bool,
    name_prefix: str,
    output_dir: str,
    document_title: str | None,
):
    table = pandas.read_json(report_path)

    formatted_table = format_table(table)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    formatted_table_and_figures = f"## {document_title}\n\n" if document_title is not None else ''

    def add_plot_vs_index(plot_name, column, ylabel, title):
        nonlocal formatted_table_and_figures
        plot_column_with_step_labels(table, column, ylabel, title)
        plot_file_name = f'{name_prefix}{plot_name}.svg'
        plt.savefig(Path(output_dir) / plot_file_name)
        formatted_table_and_figures += f"\n![{title}]({plot_file_name})"

    add_plot_vs_index('runtime-gas', 'runtime_gas', 'gas', 'Test execution cost after each step')
    add_plot_vs_index('bytecode-size', 'bytecode_size', 'size (bytes)', 'Bytecode size after each step')
    add_plot_vs_index('creation-gas', 'creation_gas', 'gas', 'Contract deployment cost after each step')

    formatted_table_and_figures += f"\n\n{formatted_table}\n"

    with open(Path(output_dir) / f'{name_prefix}table.md', 'w') as table_file:
        table_file.write(formatted_table_and_figures)

    if show_table:
        print(formatted_table)
    if show_plot:
        plt.show()


if __name__ == '__main__':
    main()
