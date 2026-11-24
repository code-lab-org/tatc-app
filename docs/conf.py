# Configuration file for the Sphinx documentation builder.
#
# For the full list of options, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import inspect
import os
import sys

# document the application from its source (also without installing it)
sys.path.insert(0, os.path.abspath("../src"))

# authentication is not needed to import the application's modules
os.environ.setdefault("TATC_AUTH", "none")

import tatc_app  # pylint: disable=wrong-import-position

# -- Project information -----------------------------------------------------

project = "TAT-C Application"
copyright = "2024, Paul T. Grogan"  # pylint: disable=redefined-builtin
author = "Paul T. Grogan"
release = tatc_app.__version__

# -- General configuration ---------------------------------------------------

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinxcontrib.autodoc_pydantic",
]

# anchors of README headings, for links such as `[Deployment](#deployment)`
myst_heading_anchors = 3

# docstrings use the Google style
napoleon_google_docstring = True
napoleon_numpy_docstring = False

# schemas list their fields (with types, defaults, and descriptions), without
# their JSON schemas, configurations, or validators
autodoc_pydantic_model_show_json = False
autodoc_pydantic_model_show_config_summary = False
autodoc_pydantic_model_show_validator_summary = False
autodoc_pydantic_model_show_validator_members = False
autodoc_pydantic_model_show_field_summary = False
autodoc_pydantic_model_member_order = "bysource"
# requests and results list the fields they inherit (but not the methods of
# pydantic models)
autodoc_default_options = {"inherited-members": "BaseModel"}
autodoc_pydantic_field_list_validators = False
autodoc_pydantic_field_show_constraints = True

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pydantic": ("https://docs.pydantic.dev/latest", None),
}

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]


def skip_methods(
    app, what, name, obj, skip, options
):  # pylint: disable=unused-argument
    """
    Skips methods: the reference documents the data of schemas, not the
    methods the server uses to process them.
    """
    return True if inspect.isroutine(obj) else None


def setup(app):
    """
    Sets up this documentation.
    """
    app.connect("autodoc-skip-member", skip_methods)


# -- Options for HTML output -------------------------------------------------

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
