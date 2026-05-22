from passive_agent.integrations.obsidian_writer import ObsidianWriter


def test_obsidian_writer_creates_vault_path(tmp_path):
    vault = tmp_path / "missing" / "vault"

    writer = ObsidianWriter(str(vault))

    assert writer.vault == vault
    assert vault.exists()
    assert vault.is_dir()
