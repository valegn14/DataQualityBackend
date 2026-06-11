# Data Analysis Backend

Esqueleto técnico para un agente de consultas a base de datos vía MCP.

## Qué contiene
- Contratos de entrada y salida.
- Capa de orquestación.
- Capa de caché de esquema.
- Abstracciones para MCP.
- Validador de SQL.
- Planner heurístico que genera SQL a partir del prompt y del esquema.
- Configuración por variables de entorno para credenciales y endpoints.
- Un entrypoint HTTP estándar para probar el agente localmente.

## Flujo esperado
1. Llega `AgentRequest` con `database_id` y `prompt`.
2. `DatabaseOrchestrator` instancia la base en MCP.
3. `SchemaCache` se consulta antes de pedir el esquema.
4. `SchemaInspector` obtiene metadatos si la caché no aplica.
5. `QueryPlanner` genera la SQL usando el prompt y el esquema.
6. `QueryValidator` valida seguridad y dialecto.
7. `MCPServerClient` ejecuta la consulta.
8. `ResultFormatter` transforma el resultado.

## Variables de entorno
Estas variables ya están preparadas para cuando conectes un API real o un MCP real:

- `LLM_PROVIDER`: proveedor del modelo, por ejemplo `ollama`.
- `LLM_API_KEY`: credencial de la API que vaya a generar o razonar sobre SQL.
- `LLM_BASE_URL`: endpoint base si usas un proveedor compatible o privado. Para Ollama suele ser `http://localhost:11434`.
- `LLM_MODEL`: modelo a usar, por ejemplo `phi4-mini`.
- `OLLAMA_BASE_URL`: URL local de Ollama, normalmente `http://localhost:11434`.
- `OLLAMA_MODEL`: nombre del modelo local, por ejemplo `phi4-mini`.
- `OLLAMA_TIMEOUT_SECONDS`: tiempo máximo de espera para el modelo local.
- `OLLAMA_ALLOW_FALLBACK`: si falla Ollama, permite usar el planner heurístico.
- `MCP_TRANSPORT`: transporte del servidor MCP, por ejemplo `http` o `stdio`.
- `MCP_SERVER_URL`: URL del servidor MCP de pruebas o real.
- `MCP_API_KEY`: credencial para acceder al servidor MCP si aplica.
- `SCHEMA_CACHE_TTL_SECONDS`: vida útil del esquema cacheado.
- `DEFAULT_MAX_ROWS`: límite por defecto de filas para las consultas.
- `ALLOW_WRITE_DEFAULT`: activa o desactiva escritura por defecto.
- `HTTP_HOST`: host donde escucha el servidor HTTP.
- `HTTP_PORT`: puerto del servidor HTTP.
- `HTTP_API_KEY`: si se define, exige `Authorization: Bearer ...` o `X-API-Key`.
- `DEMO_DATABASE_ID`: id de base de datos semilla para el modo de pruebas.
- `MCP_INSTANTIATE_PATH`, `MCP_SCHEMA_PATH`, `MCP_QUERY_PATH`, `MCP_RELEASE_PATH`: rutas HTTP del MCP.

## Cómo funciona MCP en este diseño
El agente no se conecta directamente a la base. Primero llama al MCP para instanciar una base temporal usando `database_id`. El MCP devuelve un `DatabaseHandle` y luego el mismo canal sirve para pedir el esquema, ejecutar la consulta y liberar la instancia. Eso te permite desacoplar el agente de la infraestructura real y cambiar el backend sin tocar la lógica de negocio.

En este repositorio la implementación es in-memory para pruebas, pero el contrato ya quedó listo para reemplazarla por un cliente MCP real.

## HTTP local
Puedes arrancar el servidor con:

```bash
python -m data_analysis_backend
```

Endpoints:
- `GET /health`
- `POST /query`

Streaming opcional:

```json
{
	"request_id": "req-1",
	"user_id": "user-1",
	"prompt": "show customers",
	"database_id": "demo-db",
	"stream": true
}
```

Cuando `stream` es `true`, el servidor responde con eventos SSE:
- `progress`: mensajes cortos de avance
- `final`: el resultado completo
- `done`: cierre del stream

Ejemplo de request:

```json
{
	"request_id": "req-1",
	"user_id": "user-1",
	"prompt": "show customers",
	"database_id": "demo-db"
}
```

El modo local usa un MCP en memoria para pruebas. Si `MCP_SERVER_URL` está definido, el servidor usa el cliente MCP HTTP configurable; si no, cae al modo in-memory. Si `LLM_BASE_URL` apunta a Ollama y el modelo está disponible, el planner intentará usarlo; si falla, cae al planner heurístico para que el servidor siga respondiendo.

## Siguiente implementación recomendada
- Sustituir el cliente MCP in-memory por uno real contra tu servidor.
- Conectar un generador LLM real usando `LLM_API_KEY` y `LLM_BASE_URL`.
- Añadir tests para cache hit, cache miss e invalidación por error.
- Añadir autenticación y autorización.
