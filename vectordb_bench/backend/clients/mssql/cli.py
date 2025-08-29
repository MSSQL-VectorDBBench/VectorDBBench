from typing import Annotated, Unpack

import click
from pydantic import SecretStr

from ....cli.cli import (
    CommonTypedDict,
    cli,
    click_parameter_decorators_from_typed_dict,
    run,
)
from .. import DB


class MSSQLTypedDict(CommonTypedDict):
    server: Annotated[
        str, click.option("--server", type=str, help="server url", required=True)
    ]
    database: Annotated[
        str,
        click.option("--database", type=str, help="database name", required=True),
    ]
    uid: Annotated[
        str,
        click.option("--uid", type=str, help="User id", required=False),
    ]
    pwd: Annotated[
        str,
        click.option("--pwd", type=str, help="user password", required=False),
    ]
    entraid: Annotated[
        str,
        click.option("--entraid", type=str, help="Entra Id Authentication", required=False),
    ]
    CreateIndexDOP: Annotated[
        int,
        click.option("--createindexdop", type=int, help="DOP Used for CREATE VECTOR INDEX", required=False),
    ]




@cli.command()
@click_parameter_decorators_from_typed_dict(MSSQLTypedDict)
def MSSQL(**parameters: Unpack[MSSQLTypedDict]):
    from .config import MSSQLConfig, MSSQLVectorIndexConfig

    run(
        db=DB.MSSQL,
        db_config=MSSQLConfig(
            server=parameters["server"],
            database=parameters["database"],
            uid=parameters["uid"],
            pwd=parameters["pwd"],
            entraid=parameters["entraid"],
            createindexdop=parameters["createindexdop"]
        ),
        db_case_config=MSSQLVectorIndexConfig(

        ),
        **parameters,
    )
