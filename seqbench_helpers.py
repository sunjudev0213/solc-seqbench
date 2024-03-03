import click


def fail(message: str | None = None):
    raise click.ClickException(click.style(message if message is not None else "Validation failed.", fg='red'))


def require(condition: bool, message: str | None = None):
    if not condition:
        fail(message)


def format_percent(decimal_value):
    if decimal_value is None:
        return ''

    percentage = decimal_value * 100
    prefix = (
        # Distinguish actual zero from very small differences
        '+' if round(percentage) == 0 and percentage > 0 else
        '-' if round(percentage) == 0 and percentage < 0 else
        ''
    )
    return f'{prefix}{round(percentage)}%'
