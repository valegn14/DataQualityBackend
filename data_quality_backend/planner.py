from __future__ import annotations

from dataclasses import asdict
import json
import re
import unicodedata
import time
from datetime import date, datetime, time as dtime
from abc import ABC, abstractmethod
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from .settings import AppSettings
from .contracts import QueryResult, SchemaMetadata, TableMetadata


# =========================================================
# ABSTRACT
# =========================================================
class QueryPlanner(ABC):
    @abstractmethod
    def build_sql(
        self,
        prompt: str,
        schema_metadata: SchemaMetadata,
        previous_queries: list[str] | None = None,
        previous_results: list[QueryResult] | None = None,
    ) -> str:
        raise NotImplementedError


# =========================================================
# FALLBACK
# =========================================================
class HeuristicQueryPlanner(QueryPlanner):
    def build_sql(self, prompt, schema_metadata, previous_queries=None, previous_results=None):
        print("[Heuristic] fallback activated")
        table = schema_metadata.tables[0].name
        return f"SELECT * FROM {table} LIMIT 10;"


# =========================================================
# OLLAMA PLANNER
# =========================================================
class OllamaQueryPlanner(QueryPlanner):

    def __init__(self, settings: AppSettings, fallback_planner=None):
        self._settings = settings
        self._fallback = fallback_planner or HeuristicQueryPlanner()

    def build_sql(self, prompt, schema_metadata, previous_queries=None, previous_results=None, sample_data: list[dict] | None = None):

        print("\n================ OLLAMA PLANNER ================")
        print("[Planner] prompt:", prompt)
        print("[Planner] db:", schema_metadata.database_id)

        print("[Planner] model:", self._settings.ollama_model)
        print("[Planner] base_url:", self._settings.ollama_base_url)

        print("[Planner] previous_queries:", previous_queries)
        print("[Planner] previous_results:", len(previous_results) if previous_results else 0)

        # 🔥 TIME DEBUG START
        t0 = time.time()

        try:
            sql = self._call_ollama(prompt, schema_metadata, previous_queries, previous_results, sample_data)
            print("[Planner] TOTAL TIME:", round(time.time() - t0, 2), "s")

            return sql

        except Exception as e:
            print("\n[Planner] ERROR:", repr(e))
            print("[Planner] fallback triggered\n")
            return self._fallback.build_sql(prompt, schema_metadata)

    def _call_ollama(self, prompt, schema_metadata, previous_queries, previous_results, sample_data=None):

        print("\n[Planner] CALLING OLLAMA...")

        from dataclasses import asdict
        from datetime import date, datetime, time as dtime

        # 1. dataclass → dict
        schema_dict = asdict(schema_metadata)

        # 2. convertir a formato compacto para LLM (RECOMENDADO)
        schema_str = self.simplify_schema(schema_dict)

        print("[Planner] SCHEMA SIZE:", len(schema_str))
        print("[Planner] SCHEMA:\n", schema_str)

        print("[Planner] SAMPLE DATA:", sample_data)

        final_prompt = f"""
        You are a Data Understanding and SQL Assistant.
        
        Your job is to analyze the user request and the database schema. You may generate multiple SQL queries to explore the data until you can confidently answer whether the dataset is suitable for the user's goal.
        
        ---
        
        USER TASK:
        {prompt}
        
        ---
        
        DATABASE SCHEMA:
        {schema_str}
        
        ---
        
        DATABASE TITLE:
        {sample_data[0].get('Titulo') if sample_data and sample_data[0].get('Titulo') else "No title provided."}
        
        DATABASE DESCRIPTION:
        {sample_data[0].get('Descripción') if sample_data and sample_data[0].get('Descripción') else "No description provided."}
        
        ---
        
        RULES:
        
        1. Generate SQL queries to explore the dataset. You can create as many as needed.
        
        2. Each response should contain ONE SQL query.
        
        3. After each query, you will see the results and decide if you need more information.
        
        4. When you have enough information to answer the user, provide the final evaluation in JSON format:
        
        {{
        "is_suitable": "true | false | partial",
        "quality_score": 1-10,
        "completeness_score": 1-10,
        "freshness_score": 1-10,
        "average_rating": "if applicable",
        "insights": {{
            "total_records": "number of rows",
            "last_update": "most recent update date",
            "missing_values": "percentage or count of nulls in key columns",
            "data_quality_issues": ["list of issues found"],
            "strengths": ["list of positive findings"]
        }},
        "reason": "detailed explanation based on the queries you executed",
        "missing_elements": ["what's missing to answer the user's question"],
        "recommended_use": "best use case for this dataset"
        }}
        
        ---
        
        KEY METRICS TO EVALUATE:
        
        - **Freshness**: Check 'Fecha de última actualización de datos' - when was it last updated? Is it current enough?
        - **Completeness**: Count total rows. Check for nulls in critical columns (Titulo, Descripción, etc.)
        - **Quality**: Check for duplicates, malformed data, consistency issues
        - **Sufficiency**: Does it have enough data to answer the user's question?
        
        ---
        
        STRICT RULES:
        - Keep generating SQL queries until you can answer.
        - Only output JSON when you are ready to give the final answer.
        - Do NOT mix SQL and JSON in the same response.
        """

        print("\n[Planner] FINAL PROMPT SIZE:", len(final_prompt))
        print("[Planner] --- PROMPT START ---")
        print(final_prompt[:500], "...")
        print("[Planner] --- PROMPT END ---")

        payload = json.dumps({
            "model": self._settings.ollama_model,
            "prompt": final_prompt,
            "stream": False
        }).encode()

        print("\n[Planner] sending request to Ollama...")

        req = Request(
            f"{self._settings.ollama_base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"}
        )

        start = time.time()

        try:
            with urlopen(req, timeout=self._settings.ollama_timeout_seconds) as r:
                print("[Planner] waiting response from Ollama...")

                raw = r.read().decode()

            print("[Planner] RAW RESPONSE SIZE:", len(raw))
            print("[Planner] RAW RESPONSE:", raw[:300])

            parsed = json.loads(raw)

            response = parsed.get("response", "").strip()

            print("[Planner] MODEL RESPONSE:", response)

            print("[Planner] OLLAMA TIME:", round(time.time() - start, 2), "s")

            return self._extract_sql(response)

        except (URLError, HTTPError, TimeoutError) as e:
            print("\n[Planner] OLLAMA ERROR:", repr(e))
            raise

    def simplify_schema(self, schema: dict) -> str:
        lines = []

        lines.append(f"DATABASE: {schema.get('database_id')}")
        lines.append(f"DIALECT: {schema.get('dialect')}")
        lines.append("")

        for table in schema.get("tables", []):
            lines.append(f"TABLE: {table.get('name')}")
            lines.append("")
            lines.append("COLUMNS:")

            for col in table.get("columns", []):
                name = col.get("name")
                col_type = col.get("type")

                flags = []

                if col.get("is_primary_key"):
                    flags.append("PK")

                if col.get("is_foreign_key"):
                    flags.append("FK")

                flag_str = f" [{', '.join(flags)}]" if flags else ""

                lines.append(f"- {name} ({col_type}){flag_str}")

            lines.append("")

            pk = table.get("primary_key", [])
            lines.append(f"PRIMARY KEY: {pk if pk else 'none'}")

            # relations (si existen)
            relations = table.get("relations", [])
            if relations:
                lines.append(f"RELATIONS: {relations}")
            else:
                lines.append("RELATIONS: none")

            lines.append(f"TOTAL COLUMNS: {len(table.get('columns', []))}")

        return "\n".join(lines)


    def _extract_sql(self, text: str) -> str:

        print("\n[_extract_sql] input:", text)

        text = text.strip()

        # 1. Detectar si es SQL con bloque de código
        match = re.search(r"```sql(.*?)```", text, re.S)
        if match:
            print("[_extract_sql] fenced SQL detected")
            sql = match.group(1).strip()
            if sql.lower().startswith(("select", "with")):
                return sql + ";"
            # Si el bloque SQL no empieza con SELECT/WITH, tratarlo como texto
            return sql

        # 2. Detectar si es SQL plano (sin bloques)
        if text.lower().startswith(("select", "with")):
            print("[_extract_sql] plain SQL detected")
            return text + ";"

        # 3. Detectar si es JSON (dataset evaluation)
        if text.startswith("{") and text.endswith("}"):
            print("[_extract_sql] JSON response detected, returning as-is")
            try:
                # Validar que sea JSON válido
                json.loads(text)
                return text
            except json.JSONDecodeError:
                print("[_extract_sql] invalid JSON, treating as plain text")
                return text

        # 4. Cualquier otra respuesta (texto plano, evaluación, etc.)
        print("[_extract_sql] plain text response, returning as-is")
        return text