from scripts.secret_scan import env_values, scan


def test_scanner_finds_env_values_and_token_shapes_without_printing_them(tmp_path):
    env = tmp_path / ".env"
    env.write_text("PAYPAL_CLIENT_SECRET=supersecretvalue123\nPAYPAL_ENV=sandbox\nSHORT=abc\n")
    clean, dirty, tokenish = tmp_path / "a.txt", tmp_path / "b.txt", tmp_path / "c.txt"
    clean.write_text("nothing here, sandbox")
    dirty.write_text("x supersecretvalue123 y")
    tokenish.write_text("as-" + "A" * 24)
    assert env_values(str(env)) == {"supersecretvalue123"}
    assert scan([clean], env_values(str(env))) == []
    assert scan([dirty, tokenish], env_values(str(env))) == [(str(dirty), "env_value"), (str(tokenish), "modal_token")]
