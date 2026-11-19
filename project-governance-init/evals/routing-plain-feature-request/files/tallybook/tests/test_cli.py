from click.testing import CliRunner

from tallybook.cli import main


def test_add():
    assert CliRunner().invoke(main, ["apples"]).output == "apples: +1\n"
