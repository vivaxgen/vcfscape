"""
Command Line Interface for VCFscape.
"""

import sys
import os
import click
from vcfscape import __version__
from vcfscape.ui.app import VcfscapeApp

DEFAULT_DEMO_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "examples", "pf3d7_surveillance_demo.vcf")
)
if not os.path.exists(DEFAULT_DEMO_PATH):
    # Try alternate location
    DEFAULT_DEMO_PATH = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "examples", "pf3d7_surveillance_demo.vcf")
    )


@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("vcf_file", required=False, type=click.Path(exists=False))
@click.option(
    "--demo",
    is_flag=True,
    help="Launch TUI using bundled malaria Pf3D7 surveillance demo dataset",
)
@click.option(
    "--cohorts",
    type=click.Path(exists=True),
    help="Path to TSV/CSV sample cohort metadata (SampleID, CohortName)",
)
@click.option(
    "--web",
    is_flag=True,
    help="Launch the interactive web simulator on your local system in browser",
)
@click.option(
    "--port",
    "-p",
    default=3000,
    type=int,
    help="Port to serve the local web simulator on (default: 3000)",
)
@click.option(
    "--no-browser",
    is_flag=True,
    help="Do not automatically launch web browser when running --web",
)
@click.option(
    "--token",
    default=None,
    help="Security token to protect web access (default: auto-generates secure random token)",
)
@click.option(
    "--no-token",
    is_flag=True,
    help="Disable security token authentication (allow open access)",
)
@click.version_option(version=__version__, prog_name="vcfscape")
def main(vcf_file, demo, cohorts, web, port, no_browser, token, no_token):
    """
    VCFscape - VCF inspector part of vivaxGEN Project

    High-performance Textual TUI and Web Interface to inspect multi-allelic
    and indel-dense VCF files for molecular surveillance and population genetics.
    """
    target_vcf = None
    if vcf_file:
        if not os.path.exists(vcf_file):
            click.echo(f"Error: File '{vcf_file}' does not exist.", err=True)
            sys.exit(1)
        target_vcf = os.path.abspath(vcf_file)
    elif demo:
        # Search demo VCF
        search_paths = [
            DEFAULT_DEMO_PATH,
            "/examples/pf3d7_surveillance_demo.vcf",
            os.path.join(os.getcwd(), "examples", "pf3d7_surveillance_demo.vcf"),
        ]
        for p in search_paths:
            if os.path.exists(p):
                target_vcf = p
                break
        if not target_vcf:
            click.echo("Error: Demo VCF dataset not found.", err=True)
            sys.exit(1)

    if web:
        from vcfscape.web_server import run_web_server
        run_web_server(
            port=port,
            open_browser=not no_browser,
            vcf_path=target_vcf,
            token=token,
            no_token=no_token,
        )
        return
    else:
        # Default to demo if no file provided
        search_paths = [
            DEFAULT_DEMO_PATH,
            "/examples/pf3d7_surveillance_demo.vcf",
            os.path.join(os.getcwd(), "examples", "pf3d7_surveillance_demo.vcf"),
        ]
        for p in search_paths:
            if os.path.exists(p):
                target_vcf = p
                break
        if not target_vcf:
            click.echo("Usage: vcfscape [VCF_FILE] or vcfscape --demo")
            sys.exit(1)

    app = VcfscapeApp(vcf_path=target_vcf)
    app.run()


if __name__ == "__main__":
    main()
