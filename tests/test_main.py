"""Tests for the command-line entry point."""

from pathlib import Path

from flowlang.main import main

EXAMPLES = Path(__file__).parent.parent / "examples"


def test_compiles_to_a_python_file(tmp_path, capsys):
    output = tmp_path / "smart_home.py"
    exit_code = main([str(EXAMPLES / "smart_home.flow"), "-o", str(output)])

    assert exit_code == 0
    assert "Compiled smart_home.flow" in capsys.readouterr().out
    assert "def on_sensor_update() -> None:" in output.read_text()


def test_python_flag_prints_generated_code(capsys):
    exit_code = main([str(EXAMPLES / "billing.flow"), "--python"])

    assert exit_code == 0
    assert "def calculate_total(price: float, tax: float) -> float:" in capsys.readouterr().out


def test_run_flag_runs_the_program(tmp_path, capfd):
    exit_code = main([str(EXAMPLES / "billing.flow"), "--run", "-o", str(tmp_path / "billing.py")])

    assert exit_code == 0
    assert capfd.readouterr().out.splitlines() == ["1180.0", "Standard purchase"]


def test_symbols_flag_prints_symbol_table(capsys):
    exit_code = main([str(EXAMPLES / "billing.flow"), "--symbols"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.startswith("NAME")
    assert "global > fn calculate_total" in output


def test_semantic_error_is_reported_with_position(capsys):
    exit_code = main([str(EXAMPLES / "errors" / "undeclared_variable.flow")])

    assert exit_code == 1
    assert "semantic error at line 4" in capsys.readouterr().err


def test_ast_flag_prints_syntax_tree(capsys):
    exit_code = main([str(EXAMPLES / "smart_home.flow"), "--ast"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.startswith("Program name='SmartHome'")
    assert "EventDecl name='on_sensor_update'" in output


def test_syntax_error_is_reported_with_position(capsys):
    exit_code = main([str(EXAMPLES / "errors" / "syntax_error.flow")])

    assert exit_code == 1
    assert "syntax error at line 5, column 23" in capsys.readouterr().err


def test_tokens_flag_prints_token_table(capsys):
    exit_code = main([str(EXAMPLES / "smart_home.flow"), "--tokens"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "LINE:COL" in output
    assert "IDENTIFIER      SmartHome" in output


def test_lexical_error_is_reported_with_position(capsys):
    exit_code = main([str(EXAMPLES / "errors" / "lexical_error.flow")])

    error = capsys.readouterr().err
    assert exit_code == 1
    assert "lexical error at line 4, column 30" in error
    assert "^" in error


def test_missing_file_is_an_error(capsys):
    exit_code = main(["does_not_exist.flow"])

    assert exit_code == 1
    assert "file not found" in capsys.readouterr().err


def test_wrong_extension_is_an_error(capsys):
    exit_code = main(["notes.txt"])

    assert exit_code == 1
    assert "expected a .flow file" in capsys.readouterr().err
