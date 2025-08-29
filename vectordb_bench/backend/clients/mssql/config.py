import pyodbc
import struct
from azure.identity import ManagedIdentityCredential
from pydantic import BaseModel, SecretStr
from typing import Optional
from ..api import DBConfig, DBCaseConfig, MetricType
MSSQL_CONNECTION_STRING_PLACEHOLDER="DRIVER={ODBC Driver 18 for SQL Server};SERVER=%s;DATABASE=%s;UID=%s;PWD=%s;LongAsMax=yes;Connect Timeout=30;TrustServerCertificate=Yes"

MSSQL_ENTRA_CONNECTION_STRING_PLACEHOLDER="DRIVER={ODBC Driver 18 for SQL Server};SERVER=%s;DATABASE=%s;AUTHENTICATION=ActiveDirectoryMsi;UID=%s;LongAsMax=yes;Connect Timeout=30;Encrypt=yes;TrustServerCertificate=Yes"

# --- Constants for Token Authentication ---
SQL_COPT_SS_ACCESS_TOKEN = 1256 
SQL_SERVER_TOKEN_SCOPE = "https://database.windows.net/.default"

class MSSQLConfig(DBConfig):
    server: str
    database: str
    uid: Optional[str] = None
    pwd: Optional[SecretStr] = None
    entraid: Optional[str] = None
    CreateIndexDOP: Optional[int] = 0


    def to_dict(self) -> dict:
        """
        Prepares connection parameters. If entraid is provided, it fetches a token
        manually and returns connection attributes for pyodbc.
        """
        # --- Case 1: Standard SQL Authentication ---
        if self.entraid is None:
            if not self.uid or not self.pwd:
                raise ValueError("UID and PWD must be provided for standard SQL auth.")
            
            pwd_str = self.pwd.get_secret_value()
            connection_string = (
                f"DRIVER={{ODBC Driver 18 for SQL Server}};"
                f"SERVER={self.server};"
                f"DATABASE={self.database};"
                f"UID={self.uid};"
                f"PWD={pwd_str};"
                "LongAsMax=yes;"
                "Connect Timeout=30;"
                "Encrypt=yes;"
                "TrustServerCertificate=Yes"
            )
            return {
                "connection_string": connection_string,
                "CreateIndexDOP": self.CreateIndexDOP
            }

        # --- Case 2: Entra ID Managed Identity (Manual Token Auth) ---
        print(f"Attempting to get token for User-Assigned Identity: {self.entraid}")
        
        # 1. Get credentials and token using azure-identity
        credential = ManagedIdentityCredential(client_id=self.entraid)
        access_token = credential.get_token(SQL_SERVER_TOKEN_SCOPE)
        token_bytes = access_token.token.encode("UTF-16-LE")
        
        # 2. Pack the token for the driver
        token_struct = struct.pack(f'<I{len(token_bytes)}s', len(token_bytes), token_bytes)
        
        print("Token acquired successfully.")

        # 3. Create the connection string WITHOUT auth keywords (UID, PWD, AUTHENTICATION)
        connection_string = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={self.server};"
            f"DATABASE={self.database};"
            "LongAsMax=yes;"
            "Connect Timeout=30;"
            "Encrypt=yes;"
            "TrustServerCertificate=Yes"
        )
        
        # 4. Return both the string and the token attributes
        return {
            "connection_string": connection_string,
            "attrs_before": {SQL_COPT_SS_ACCESS_TOKEN: token_struct},
            "CreateIndexDOP": self.CreateIndexDOP
        }


class MSSQLVectorIndexConfig(BaseModel, DBCaseConfig):
    metric_type: MetricType | None = None
    efSearch: int | None = 48
    CreateIndexDOP: int | None = 0

    def parse_metric(self) -> str: 
        if self.metric_type == MetricType.L2:
            return "euclidean"
        elif self.metric_type == MetricType.IP:
            return "dot"
        return "cosine"
    
    def index_param(self) -> dict:
        return {
            "lists" : self.lists,
            "metric" : self.parse_metric(),
            "CreateIndexDOP": self.CreateIndexDOP
        }
    
    def search_param(self) -> dict:
        return {
            "efSearch" : self.efSearch,
            "metric" : self.parse_metric(),
            "CreateIndexDOP": self.CreateIndexDOP
        }
