# Validação executada

Revisão de aplicabilidade de métricas: **06/10/2026**, timezone do projeto `America/Cuiaba`.

## Resultados

| Verificação | Resultado |
|---|---|
| Suíte completa no host Python 3.13.7, incluindo MySQL 8.4 | **80 passed**, sem warnings |
| Suíte na imagem final Python 3.12 | **78 passed, 2 skipped**, sem warnings |
| Imports de todos os módulos do pacote app | **36 módulos importados** |
| Ruff | **All checks passed** |
| Compileall de app, alembic e tests | **Sucesso** |
| Migrations 0001/0002: upgrade/downgrade em SQLite e MySQL 8.4 | **Sucesso**, inclusive bases com duplicidades |
| Comparação de metadata/modelos/schema | **Sem diferenças** |
| Alembic check no MySQL, executado pela CLI e nos testes | **No new upgrade operations detected** |
| Geração offline de SQL MySQL | **Sucesso**, inclui DATETIME(6), constraints e views |
| Seis views, demografia, novos campos de performance e taxas com reach zero | **Sucesso** |
| Lock MySQL entre duas instâncias do serviço | **Sucesso**, segunda execução rejeitada |
| Docker build da imagem final `instagram-bi:local` | **Sucesso** |
| Docker Compose config com valores fictícios (validação inicial de 05/10) | **Sucesso** |
| Boot do container com migrations automáticas (validação inicial de 05/10) | **Sucesso** |
| HEALTHCHECK Docker (validação inicial de 05/10) | **healthy** |
| Smoke HTTP (validação inicial de 05/10) | **Sucesso** |

A execução dentro da imagem pula os dois casos que exigem MySQL externo; ambos foram
executados no host contra um MySQL 8.4 temporário em Docker. Os testes na
imagem foram montados em modo somente leitura, e pytest foi instalado em `/tmp` de um
container descartável; a imagem final contém apenas dependências de runtime.

O smoke test iniciou a aplicação com `COLLECT_ON_STARTUP=false` e `SCHEDULER_ENABLED=false`,
para impedir qualquer chamada real à Meta. O teste de coleta usa HTTPX MockTransport,
inclusive quando grava no MySQL real de teste. **Nenhuma credencial real foi utilizada e
nenhuma consulta autenticada à API real do Instagram foi feita.**

## Casos cobertos

- Paginação completa e proteção contra cursor repetido.
- Bearer apenas no header, sem seguir URLs next que contenham token/outro host.
- Retry de timeout/429/5xx/rate-limit e erros temporários da Meta, backoff e Retry-After.
- Ausência de retry para erros OAuth e 4xx permanentes.
- Parsers de values, total_value, breakdowns, números decimais e formatos incompletos.
- Follows/unfollows separados do delta; labels desconhecidos permanecem NULL.
- Uma métrica inválida não impede salvar as demais; métricas ausentes permanecem NULL.
- Upsert de mídia e preservação de tipos futuros, first_seen e identidade.
- Recoletas diárias comparadas ao dia anterior; primeiro delta NULL.
- Vários snapshots no mesmo dia sem sobrescrever histórico; microssegundos preservados.
- Lookback aplicado apenas aos insights, conservando mídias antigas.
- Falha em página posterior preserva dados das páginas anteriores.
- Demografia indisponível não falha a coleta principal.
- Auditoria, recuperação de RUNNING abandonado, cancelamento e liberação do lock.
- Health/status/auth, erro HTTP sanitizado e chave somente em header.
- Redação de secrets, URLs codificadas e traceback; validação e repr de secrets.
- Rejeição de datetime naive, armazenamento/leitura UTC e Unicode/emoji no MySQL.
- Migrations, integridade de schema, views e divisão por zero.
- UPSERT de account insights por conta/período, atualizando métricas e collected_at.
- UPSERT de demografia por bucket/data, atualizando valor e collected_at.
- Reposts opcional: valor retornado ou NULL com warning para métrica incompatível.
- Upgrade incremental com duplicidades: mantém a coleta mais recente e o maior id em empates.
- Constraints rejeitam duplicidades após upgrade; downgrade/reupgrade sem divergência de schema.
- View de demografia com todos os campos solicitados e cinco novos campos de media performance.
- Conteúdo de instagram_media_insights idêntico antes/depois de upgrade e downgrade de 0002.
- Arquivo 0001_initial.py preservado, confirmado por SHA256 antes/depois da revisão.
- REELS não solicita follows/profile_visits; suas colunas continuam NULL sem warning.
- FEED IMAGE/CAROUSEL_ALBUM consulta follows/profile_visits e não solicita métricas de vídeo.
- Métricas NOT_APPLICABLE são registradas em DEBUG; job REELS termina SUCCESS com warnings_count=0.
- Account profile_visits: incompatibilidade explícita ou data vazio é opcional/UNSUPPORTED sem warning.
- Resposta inesperada ou valor malformado de profile_visits ainda gera warning.
- Breakdowns não reconhecidos de follows_and_unfollows continuam gerando warning.
- A classificação opcional não suprime OAuth, erro de permissão, rate limit ou HTTP 5xx.

Esta revisão usa a matriz empírica informada pelo usuário como política de seleção. A
implementação foi validada com fixtures simuladas, sem novas chamadas autenticadas à Meta.
Nenhuma tabela foi alterada e nenhuma migration nova foi criada.

## Reproduzir a suíte

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
python -m compileall -q app alembic tests
docker build -t instagram-bi:local .
```

Para habilitar o teste opcional com MySQL, use exclusivamente um banco descartável. O
teste aplica migrations e executa downgrade, removendo suas tabelas ao terminar:

```powershell
docker run -d --name instagram-bi-test-mysql `
  -p 127.0.0.1:13306:3306 `
  -e MYSQL_DATABASE=instagram_bi_test -e MYSQL_USER=ig_test `
  -e MYSQL_PASSWORD=development-only -e MYSQL_ROOT_PASSWORD=development-root-only mysql:8.4
# Aguarde o MySQL aceitar conexões antes de rodar:
$env:RUN_MYSQL_INTEGRATION = '1'
python -m pytest -q
Remove-Item Env:RUN_MYSQL_INTEGRATION
docker rm -f -v instagram-bi-test-mysql
```

As strings acima são credenciais fictícias para o teste, nunca para produção. O teste
usa apenas o database fixo `instagram_bi_test`, host `127.0.0.1` e porta `13306`.

## Validação pendente com a conta real

1. Consentimento Instagram Login, identidade retornada por `/me`, escopos e validade do token.
2. Disponibilidade dos campos/métricas na versão selecionada, em cada tipo/idade de mídia.
3. Semântica e labels do breakdown follows_and_unfollows: o parser só aceita ações
   FOLLOW/FOLLOWS e UNFOLLOW/UNFOLLOWS, ou valores nomeados equivalentes; desconhecidos são NULL.
4. A matriz de FEED IMAGE/CAROUSEL_ALBUM e REELS foi validada na conta pelo usuário. Revalidar
   em outras contas/versões; watch time/skip rate e outras métricas podem mudar de disponibilidade.
5. Demografia, requisitos de tamanho de audiência e formato efetivamente retornado.
6. Latência dos insights, completude das mídias acessíveis ao token e limites de chamadas.
7. Conectividade/driver/gateway do Power BI e credenciais SELECT no ambiente do usuário.

O backend não reconstrói histórico anterior à instalação, não recupera mídias inacessíveis
ou removidas e não implementa renovação automática de tokens. `/me/media` não garante a
enumeração de Stories. A integração guarda os tipos realmente retornados pela API.

Os containers temporários de validação são removidos ao final do desenvolvimento. A imagem
`instagram-bi:local` e o venv local permanecem disponíveis para execução do projeto.
