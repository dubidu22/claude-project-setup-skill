import click


@click.command()
@click.argument("name")
def main(name: str) -> None:
    """Add one to the tally called NAME."""
    click.echo(f"{name}: +1")


if __name__ == "__main__":
    main()
