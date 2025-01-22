"""Wrapper around MSSQL"""

import logging
from contextlib import contextmanager
from typing import Any, Generator, Optional, Tuple, Sequence

from ..api import VectorDB, DBCaseConfig

import pyodbc
import json

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
        self.drop_old = drop_old

        log.info("db_case_config: " + str(db_case_config))

        log.info(f"Connecting to MSSQL...")
        #log.info(self.db_config['connection_string'])
        cnxn = pyodbc.connect(self.db_config['connection_string'] + ';LongAsMax=yes;')     
        cursor = cnxn.cursor()

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
                drop table if exists [{self.schema_name}].[{self.table_name}]
            """)           
            cnxn.commit()

        log.info(f"Creating vector table...")
        cursor.execute(f""" 
            if object_id('[{self.schema_name}].[{self.table_name}]') is null begin
                create table [{self.schema_name}].[{self.table_name}] (
                    id int not null primary key clustered,
                    [vector] vector({self.dim}) not null
                )                
            end
        """)
        cnxn.commit()
            
        log.info(f"Creating table type...")
        cursor.execute(f""" 
            if type_id('dbo.vector_payload') is null begin
                create type dbo.vector_payload as table
                (
                    id int not null,
                    [vector] vector({self.dim}) not null
                )
            end
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
                insert into [{self.schema_name}].[{self.table_name}] (id, [vector]) select id, [vector] from @payload;
            end
        """)
        cnxn.commit()

        self.hndl = cursor.prepareStatement("""        
                select 
                    t.id
                from
                    vector_search(
                        table = [{self.schema_name}].[{self.table_name}] AS t, 
                        column = [vector], 
                        similar_to = ?,
                        metric = '{metric_function}', 
                        top_n = ?
                    ) AS s
                where
                    v.id >= ?                
                """)

        cursor.close()
        cnxn.close()
            
    @contextmanager
    def init(self) -> Generator[None, None, None]:
        cnxn = pyodbc.connect(self.db_config['connection_string'] + ';LongAsMax=yes;')     
        self.cnxn = cnxn    
        cnxn.autocommit = True
        self.cursor = cnxn.cursor()
        try:
            yield
        finally: 
            self.cursor.close()
            self.cnxn.close()
            self.cursor = None
            self.cnxn = None

    def ready_to_load(self):
        log.info(f"MSSQL ready to load")
        pass

    def optimize(self):        
        log.info(f"MSSQL optimize")
        search_param = self.case_config.search_param()
        metric_function = search_param["metric"]
        cursor = self.cursor
        if self.drop_old:
            cursor.execute(f"""            
                if exists(select * from sys.indexes where object_id = object_id('[{self.schema_name}].[{self.table_name}]') and type=8)
                begin
                    drop index vec_idx on [{self.schema_name}].[{self.table_name}];
                end
                """, 
                )
        
        cursor.execute(f"""            
            create vector index vec_idx on [{self.schema_name}].[{self.table_name}]([vector]) with (metric = '{metric_function}', type = 'DiskANN'); 
            """                
            )

    def ready_to_search(self):
        log.info(f"MSSQL ready to search")
        pass
    
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
            params = [(metadata[i], json.dumps(embeddings[i])) for i in range(len(metadata))]

            log.info(f'Loading table...')
            cursor = self.cursor          
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
        metric_function = 'euclidean' #search_param["metric"]
        #efSearch = search_param["efSearch"]
        #log.info(f'Query top:{k} metric:{metric_fun} filters:{filters} params: {search_param} timeout:{timeout}...')
        cursor = self.cursor
        
        cursor.executePreparedStatement(self.hndl, json.dumps(query), k)

        #if filters:
            # select top(?) v.id from [{self.schema_name}].[{self.table_name}] v where v.id >= ? order by vector_distance(?, cast(? as varchar({self.dim})), v.[vector])
        #    cursor.execute(f"""        
        #        select 
        #            t.id
        #        from
        #            vector_search(
        #                table = [{self.schema_name}].[{self.table_name}] AS t, 
        #                column = [vector], 
        #                similar_to = ?,
        #                metric = '{metric_function}', 
        #                top_n = ?
        #            ) AS s
        #        where
        #            v.id >= ?                
        #        """, 
        #        json.dumps(query),                      
        #        k,                    
        #        int(filters.get('id')),                                  
        #        )
        #else:
            # select top(?) v.id from [{self.schema_name}].[{self.table_name}] v order by vector_distance(?, cast(? as vector({self.dim})), v.[vector]) 
        #    cursor.execute(f"""
        #        declare @v vector({self.dim}) = ?;        
        #        select 
        #            t.id
        #        from
        #            vector_search(
        #                table = [{self.schema_name}].[{self.table_name}] AS t, 
        #                column = [vector], 
        #                similar_to = @v,
        #                metric = '{metric_function}', 
        #                top_n = ?
        #            ) AS s
        #        order by
        #            t.id   
        #        """, 
        #        json.dumps(query),      
        #        k,                                                      
        #        )
        rows = cursor.fetchall()
        res = [row.id for row in rows]
        return res
        
        
