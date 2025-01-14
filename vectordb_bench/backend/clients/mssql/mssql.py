"""Wrapper around MSSQL"""

import logging
from contextlib import contextmanager
from typing import Any, Generator, Optional, Tuple, Sequence

from ..api import VectorDB, DBCaseConfig

import pyodbc
import struct
import time

log = logging.getLogger(__name__) 

class MSSQL(VectorDB):    
    def __init__(
        self,
        dim: int,
        db_config: dict,
        db_case_config: DBCaseConfig,
        collection_name: str = "vector",
        drop_old: bool = False,
        **kwargs,
    ):
        self.db_config = db_config
        self.case_config = db_case_config
        self.table_name = collection_name + "_" + str(dim)
        self.dim = dim
        self.schema_name = "benchmark"
        self.prepared = False
        log.info("db_case_config: " + str(db_case_config))

        log.info(f"Connecting to MSSQL...")
        
        cnxn = pyodbc.connect(self.db_config['connection_string'])     
        cursor = cnxn.cursor()

        log.info(f"Start Prepare")
        cursor.prepareStatement("SELECT ?", [1])
        ret = cursor.executePreparedStatement("SELECT ?", [2])
        cnxn.commit()
        cursor.prepareStatement("SELECT ?", [1])
        ret = cursor.executePreparedStatement("SELECT ?", [3])
        rows = cursor.fetchall()
        res = [row for row in rows]
        
        cnxn.commit()

        log.info(res)

        log.info(f"Creating schema...")
        cursor.execute(f""" 
            if (schema_id('{self.schema_name}') is null) begin
                exec('create schema [{self.schema_name}] authorization [dbo];')
            end;
        """)
        cnxn.commit()
        
        if drop_old:
            log.info(f"Dropping existing table...")
            cursor.execute(f""" 
                drop table if exists dbo.graphnode
            """)           
            cnxn.commit()

        log.info(f"Creating vector table...")
        create_table = f""" 
            if object_id('dbo.graphnode') is null begin
                create table dbo.graphnode (
                    id int not null primary key clustered,
                    embedding vector({self.dim}) not null
                )                
            end
        """
        log.info(f"vector table schema: {create_table}")   
        cursor.execute(create_table)
        cnxn.commit()

        log.info(f"Creating table type...")
        cursor.execute(f""" 
	      drop procedure if exists stp_load_vectors
          drop type if exists dbo.vector_payload
          drop table if exists GTQuery
          create type dbo.vector_payload as table
            (
                id int not null,
                embedding vector({self.dim}) not null
            )
        """)
        cursor.commit()

        log.info(f"Creating stored procedure...")
        cursor.execute(f""" 
            create or alter procedure dbo.stp_load_vectors
            @dummy int,
            @payload dbo.vector_payload readonly
            as
            begin
                set nocount on
                insert into dbo.graphnode (id, embedding) select id, cast(cast([embedding] as nvarchar(max)) as vector({self.dim})) from @payload;
            end
        """)
        cnxn.commit()

        #self.cursor = cnxn.cursor()
        #log.info(f"Creating Clustered Index on id...")
        #cursor.execute(f""" 
        #    CREATE UNIQUE CLUSTERED INDEX vec_id_idx ON graphnode (id)
        #""")
        #cnxn.commit()
        
        '''
        log.info(f"Creating Vector Index...")
        cursor.execute(f""" 
            CREATE VECTOR INDEX vec_idx on [GRAPHNODE]([EMBEDDING]) WITH (METRIC = 'euclidean', TYPE = 'DiskANN', DROP_EXISTING = ON)
        """)
        cnxn.commit()

        log.info(f"Wait for Vector Index Creation...")
        time.sleep(1800)
        log.info(f"Done Waiting for Vector Index Creation...")

        '''
        cursor.close()
        cnxn.close()
    @contextmanager
    def init(self) -> Generator[None, None, None]:
        cnxn = pyodbc.connect(self.db_config['connection_string'])     
        self.cnxn = cnxn    
        cnxn.autocommit = True
        self.cursor = cnxn.cursor()
        yield 
        self.cursor.close()
        self.cnxn.close()

    def create_index(self):
        cnxn = pyodbc.connect(self.db_config['connection_string'])     
        cursor = cnxn.cursor()
        log.info(f"Creating Vector Index...")
        cursor.execute(f""" 
            CREATE VECTOR INDEX vec_idx on [GRAPHNODE]([EMBEDDING]) WITH (METRIC = 'euclidean', TYPE = 'DiskANN', DROP_EXISTING = ON)
        """)
        cnxn.commit()

        log.info(f"Wait for Vector Index Creation...")
        #time.sleep(1800)
        log.info(f"Done Waiting for Vector Index Creation...")

        log.info(f"Creating Test Dataset...")
        cursor.execute(f""" 
            SELECT TOP 1 * INTO GTQuery FROM dbo.graphnode WHERE id = 1
        """)
        cnxn.commit()
        cursor.close()
        cnxn.close()

    def ready_to_load(self):
        log.info(f"MSSQL ready to load")
        pass

    def optimize(self):
        log.info(f"MSSQL optimize")
        pass

    def ready_to_search(self):
        log.info(f"MSSQL ready to search")
        pass

    def array_to_vector(self, a:list[float]) -> str:
        # TODO, for now, create a string representation of the vector
        # Cast that to VARCHAR and then to Vector, this is temporary
        res = '['
        
        for f in a:
            res += str(f) + ', '

        res = res[:-2]
        res += ']'

        return res
        return b
    
    def insert_embeddings(
        self,
        embeddings: list[list[float]],
        metadata: list[int],
        **kwargs: Any,
    ) -> Tuple[int, Optional[Exception]]:   
        try:            
            log.info(f'Loading batch of {len(metadata)} vectors...')
            #return len(metadata), None
        
            log.info(f'Generating param list...')
            params = [(metadata[i], self.array_to_vector(embeddings[i])) for i in range(len(metadata))]

            log.info(f'Loading table...')
            cursor = self.cursor
            #cursor.fast_executemany = True               
            cursor.execute("EXEC dbo.stp_load_vectors @dummy=?, @payload=?", (1, params))     

            return len(metadata), None
        except Exception as e:
            #cursor.rollback()
            log.warning(f"Failed to insert data into vector table ([{self.schema_name}].[{self.table_name}]), error: {e}")   
            return 0, e

    def search_embedding(        
        self,
        query: list[float],
        k: int = 100,
        filters: dict | None = None,
        timeout: int | None = None,
    ) -> list[int]:        
        search_param = self.case_config.search_param()
        metric_function = search_param["metric"]
        #efSearch = search_param["efSearch"]
        #log.info(f'Query top:{k} metric:{metric_fun} filters:{filters} params: {search_param} timeout:{timeout}...')
        #cursor = self.cursor
        #cursor.execute("SELECT 1")
        if self.prepared == False:

            cnxn = pyodbc.connect(self.db_config['connection_string'])
            self.cnxn = cnxn
            cnxn = self.cnxn
            cnxn.autocommit = True
            self.cursor = cnxn.cursor()
            cursor = self.cursor
            log.info(f'Start Prepare...')
            cursor.prepareStatement(f"""
                SELECT ann.id FROM VECTOR_SEARCH(
                    TABLE       = [{self.schema_name}].[{self.table_name}] AS src, 
                    COLUMN      = vector, 
                    SIMILAR_TO  = (SELECT vector FROM [{self.schema_name}].[{self.table_name}] WHERE id = 1), 
                    METRIC      = 'euclidean', 
                    TOP_N       = ?
                ) AS ann
            """, k)
            log.info(f'End Prepare...')
            self.prepared = True
        
        #log.info(f'1End Prepare...')
        #cursor.prepareStatement("SELECT ?", [1])
        #ret = cursor.executePreparedStatement("SELECT ?", [2])
        #cnxn.commit()
        #cursor.prepareStatement("SELECT ?", [1])
        #log.info(f'2End Prepare...')
        #ret = cursor.executePreparedStatement("SELECT ?", [3])
        
        #log.info(f'4End Prepare...')
        #rows = cursor.fetchall()
        #res = [row for row in rows]
        
        #cnxn.commit()

        #log.info(res)
        #log.info(f'3End Prepare...')

        cnxn = self.cnxn
        cursor = self.cursor
        #log.info(f'Start Execute...')
        #cursor.executePreparedStatement(f""" """, k)
        #log.info(f'End Execute...')
        #cursor.execute("SELECT 1")
        
        #if filters:
        #    cursor.execute(f"""            
        #        select top(?) v.id from [{self.schema_name}].[{self.table_name}] v where v.id >= ? order by vector_distance(cast(? as varchar(20)), cast(cast(? as nvarchar(max)) as vector({self.dim})), v.[vector])
        #        """, 
        #        k,                
        #        int(filters.get('id')),
        #        metric_function,
        #        self.array_to_vector(query)
        #        )
        #else:
        #    cursor.execute(f"""
        #        SELECT ann.id FROM 
        #            VECTOR_SEARCH(
        #                TABLE		= dbo.graphnode AS src,
        #                COLUMN		= embedding,
        #                SIMILAR_TO	= (SELECT embedding FROM dbo.graphnode WHERE id = 1),
        #                METRIC		= 'euclidean',
        #                TOP_N		= ?
        #        ) AS ann
        #        """,
        #        #self.array_to_vector(query),
        #        #"'" + metric_function + "'",
        #        k
        #        )
            # TODO: alter the id per user
            #cursor.execute(f"""            
            #    select top(?) v.id from [{self.schema_name}].[{self.table_name}] v order by vector_distance(cast(? as varchar(20)), cast(cast(? as nvarchar(max)) as vector({self.dim})), v.[vector])
            #    """,
            #    k,
            #    metric_function,
            #    self.array_to_vector(query)
            #    )
        rows = cursor.fetchall()
        res = [row.id for row in rows]
        #log.info(res)
        cursor.commit()
        #log.info(f'Start Execute...')
        #cursor.executePreparedStatement(f"""
        #""", k)
        #log.info(f'End Execute...')
        #cnxn.commit()
        #quit()`
        return res
        
        
