"""Sphinx configuration for the independent CLI."""

import importlib.metadata

project = "hackerrank-cli"
author = "Adam Dangoor"
release = importlib.metadata.version(distribution_name="hackerrank-cli")
extensions = ["sphinx_click.ext", "sphinxcontrib.spelling"]
html_theme = "furo"
nitpicky = True
html_theme_options = {
    "source_repository": "https://github.com/adamtheturtle/hackerrank-cli/",
    "source_branch": "main",
    "source_directory": "docs/source/",
}

spelling_word_list_filename = "../../spelling_private_dict.txt"
