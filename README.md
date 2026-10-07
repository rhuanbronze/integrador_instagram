# Instagram BI

Backend de coleta **somente leitura** para contas profissionais do Instagram, com FastAPI,
Instagram API com Instagram Login, MySQL 8 e views para Power BI. Nenhum endpoint publica,
envia mensagens, responde comentários ou altera a conta do Instagram.

## 1. Objetivo e limites dos dados

Guardar metadados da conta, seguidores diários, insights da conta, publicações, histórico de
insights por publicação e demografia opcional. Apenas dados efetivamente retornados pela API
são gravados. Métricas indisponíveis são `NULL`, com warning, sem inventar zeros.

`followers_delta` é a variação líquida em relação ao snapshot diário anterior. `follows` e
`unfollows` são ações retornadas pelo breakdown da API; nunca são deduzidos do delta. O
primeiro delta é `NULL`. Se houver dias sem coleta, o delta compara com a última data coletada,
portanto não equivale necessariamente a uma variação de exatamente 24 horas.

`media_count` é o total atual informado pela conta. Para contar publicações em um período,
filtre `instagram_media.published_at`. O backend mantém publicações antigas mesmo quando
ficam fora do lookback de insights.

## 2. Arquitetura

```text
Instagram API (GET + Authorization: Bearer)
          ↓ HTTPX / retries / cursor pagination / isolated metrics
Coletores de conta, insights, mídias e demografia
          ↓ SQLAlchemy / commits incrementais
MySQL: dados atuais + snapshots históricos + auditoria ETL
          ↓ seis views SQL
Power BI

FastAPI → jobs manuais autenticados
APScheduler → jobs periódicos
Alembic → schema e views versionados
```

O cliente só implementa GET. Cada métrica de insights é consultada separadamente: o custo
é mais requisições, em troca de isolamento entre métricas incompatíveis. Não há SDK da Meta,
fila externa ou armazenamento de tokens. A execução aceita uma conta por instância; as
tabelas têm chaves de conta para futura expansão, sem supor suporte multi-token já existente.

Datetimes no Python são timezone-aware. `DATETIME(6)` no MySQL contém UTC sem offset; o
tipo SQLAlchemy reconstrói UTC ao ler. `TIMEZONE` define datas dos snapshots, limites do
dia anterior e timezone do scheduler. IDs locais são BIGINT auto increment; IDs Instagram
são strings únicas. A conta autenticada é descoberta por `/me`; um ID configurado diferente
do retornado encerra o job para impedir associação incorreta.

## 3. Requisitos

- Python 3.12+ ou Docker com engine ativo.
- MySQL 8+ com `utf8mb4`; Compose usa MySQL 8.4.
- Conta profissional Business/Creator e app configurado para Instagram Login.
- Token com permissões de leitura de perfil/mídias e de insights.
- Rede de saída HTTPS para `graph.instagram.com` e acesso TCP ao MySQL.

## 4. Configuração do Instagram

1. Crie/configure o app no Meta for Developers para **Instagram API with Instagram Login**.
2. Vincule e autorize a conta profissional no fluxo de Instagram Login. Configure redirect URI,
   usuários de teste e acesso do app conforme o modo do app e a documentação vigente.
3. Obtenha o token por esse fluxo; confirme os escopos de leitura de dados e insights,
   incluindo `instagram_business_basic` e `instagram_business_manage_insights` quando
   disponíveis para seu app. Não conceda publicação ou mensagens para esta aplicação.
4. Cadastre o token somente no ambiente de execução: `.env` local ignorado pelo Git ou
   secret/environment variable no Dokploy. O código não implementa uma tela OAuth e não
   troca, renova ou persiste tokens automaticamente.
5. Deixe `INSTAGRAM_USER_ID` vazio para descoberta automática, ou preencha o ID da mesma conta.

Referências primárias:

- [Instagram Login — Meta](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/)
- [Insights — Meta](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/insights/)
- [Coleção oficial da Meta no Postman](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api)
- [Nomes de métricas no SDK oficial da Meta](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/insightsresult.py)

Os nomes específicos de Reels são `ig_reels_avg_watch_time`,
`ig_reels_video_view_total_time` e `reels_skip_rate`, mapeados às colunas locais de watch time
e skip rate. Sua disponibilidade com Instagram Login e a versão configurada precisa ser
validada na conta real. O projeto tenta coletá-los e aceita ausência; não afirma suporte
universal. As referências da Meta podem mudar ou exigir autenticação. Não foram feitas
chamadas com tokens reais durante o desenvolvimento.

## Gerenciamento do Access Token

**A aplicação depende do token configurado em `INSTAGRAM_ACCESS_TOKEN`.** Expiração ou
revogação causa falha OAuth nos jobs até que essa variável seja atualizada com um token
válido e a aplicação seja reiniciada/reimplantada. Consulte `/api/status` para identificar
a falha. Não há renovação automática de token nesta versão. Atualize o secret no Dokploy
ou o ambiente local; não registre o token em logs, URLs ou no banco.

## 5. Variáveis de ambiente

Copie `.env.example` para `.env` e preencha as credenciais. Secrets vazios são rejeitados.

| Variável | Default/exemplo | Uso |
|---|---|---|
| `META_API_VERSION` | `v26.0` | Única configuração de versão; URL `https://graph.instagram.com/{versão}` |
| `INSTAGRAM_ACCESS_TOKEN` | obrigatório | Token de Instagram Login; apenas cabeçalho Bearer |
| `INSTAGRAM_USER_ID` | vazio | Descoberto por `/me?fields=id,username` |
| `MYSQL_HOST` | `mysql` no Compose | Endereço do MySQL; externo no Dokploy |
| `MYSQL_PORT` | `3306` | Porta TCP |
| `MYSQL_DATABASE` | `instagram_bi` | Database previamente criado |
| `MYSQL_USER` | `instagram_bi` | Usuário da aplicação |
| `MYSQL_PASSWORD` | obrigatório | Senha do MySQL |
| `TIMEZONE` | `America/Cuiaba` | Calendário dos snapshots/scheduler |
| `ACCOUNT_CRON_HOUR` | `7` | Hora diária do job account (0–23) |
| `ACCOUNT_CRON_MINUTE` | `0` | Minuto do job account (0–59) |
| `MEDIA_CRON_HOURS` | `0,6,12,18` | Horas do job media, separadas por vírgula, sem espaços (0–23) |
| `MEDIA_CRON_MINUTE` | `0` | Minuto do job media (0–59) |
| `MEDIA_INSIGHTS_LOOKBACK_DAYS` | `90` | Idade máxima para novas coletas de insights de mídia |
| `REQUEST_TIMEOUT_SECONDS` | `30` | Timeout HTTP por etapa da requisição |
| `REQUEST_MAX_RETRIES` | `3` | Retries além da chamada inicial |
| `ADMIN_API_KEY` | obrigatório | Chave dos POSTs, enviada por `X-API-Key` |
| `LOG_LEVEL` | `INFO` | DEBUG, INFO, WARNING, ERROR ou CRITICAL |
| `AUDIENCE_COLLECTION_ENABLED` | `true` | Demografia opcional |
| `COLLECT_ON_STARTUP` | `true` | Executa account seguido de media a cada inicialização |
| `SCHEDULER_ENABLED` | `true` | Habilita os agendamentos automáticos |
| `MYSQL_ROOT_PASSWORD` | opcional no Compose | Apenas MySQL local; default igual à senha local |

O usuário MySQL precisa de SELECT/INSERT/UPDATE e permissões de DDL para migrations
(CREATE, ALTER, INDEX, DROP, CREATE VIEW). O usuário do Power BI deve ter somente SELECT.
Não use o usuário root na aplicação. O database externo deve existir antes de iniciar.

## 6. Execução local com Python

PowerShell:

```powershell
Copy-Item .env.example .env
# Edite .env com seus valores antes de continuar.
python -m venv .venv
.venv/Scripts/Activate.ps1
python -m pip install -r requirements-dev.txt
# Para executar Python no host, use MYSQL_HOST=127.0.0.1 no .env.
docker compose up -d mysql
python -m alembic upgrade head
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log
```

Linux/macOS: ative o venv com `source .venv/bin/activate`. O servidor valida MySQL e a
presença das migrations antes de servir; o job inicial valida `/me`, faz upsert da conta,
snapshot diário, account insights/demografia, pagina todas as mídias e coleta insights
recentes, registrando uma execução ETL para cada job.

A coleta inicial é assíncrona para permitir consultar health/status durante o processamento.
Um token inválido marca a execução como FAILED; consulte `/api/status`. `health=ok` informa
disponibilidade do servidor/banco, não confirma validade do token nem atualidade dos dados.

## 7. Docker e Compose

```sh
docker compose up -d --build
docker compose logs -f instagram-bi
docker compose ps
```

O Compose injeta `MYSQL_HOST=mysql` e mantém a porta do MySQL restrita ao localhost.
O volume nomeado `mysql_data` pertence somente ao banco. A aplicação não precisa de volumes.
O container roda como UID 10001, instala apenas dependências de runtime e expõe a porta 8000.
Seu entrypoint aplica migrations e executa Uvicorn em um único worker. O HEALTHCHECK chama
`/health`. `.dockerignore` exclui `.env`, logs, venv e testes da imagem.

Para MySQL externo:

```sh
docker build -t instagram-bi:local .
docker run --name instagram-bi --env-file .env -p 8000:8000 instagram-bi:local
```

Neste caso configure `MYSQL_HOST` com o host externo, não `mysql` ou `localhost`.

## 8. Dokploy

1. Cadastre o repositório como aplicação Dockerfile, contexto `.`, arquivo `Dockerfile`.
2. Configure todas as variáveis obrigatórias da seção 5 e os horários desejados.
3. Use `MYSQL_HOST`/`MYSQL_PORT` da rede privada do banco externo. Não use localhost para
   acessar outro container. Verifique DNS, firewall e permissões do usuário.
4. Configure a porta interna **8000** e health check `/health`. Use HTTPS no proxy público.
5. Execute uma réplica e um worker Uvicorn por aplicação. O lock MySQL bloqueia jobs simultâneos,
   mas o scheduler de cada réplica teria agenda própria; não é um scheduler distribuído.
6. Faça backup do banco antes de futuras migrations. A migration inicial é automática no boot;
   evite múltiplos deploys concorrentes executando DDL no mesmo schema.

Não há arquivos de estado local. Tokens e senhas ficam no ambiente do container. Rotacione
o token no Dokploy quando necessário e redeploy. Os logs omitem payloads/headers HTTP e
mensagens brutas da Meta; secrets conhecidos e parâmetros sensíveis são mascarados.

## 9. Estrutura do banco e migrations

| Tabela | Finalidade |
|---|---|
| `instagram_accounts` | Cadastro da conta; `instagram_user_id` único |
| `instagram_account_daily` | Um snapshot por conta/data local; delta líquido |
| `instagram_account_insights` | Uma linha por conta/período; totais diários, incluindo reposts nullable |
| `instagram_media` | Metadados atuais; `instagram_media_id` único |
| `instagram_media_insights` | Snapshots acumulados; unique `(media_id, collected_at)` |
| `instagram_audience_demographics` | Uma linha por conta/data/audiência/breakdown/bucket |
| `etl_runs` | Auditoria de account/media, contadores, warnings, falhas |

Account insights usam `period_start = period_end = dia anterior` (datas inclusivas), com
`since` e `until` UTC delimitando esse dia, fim exclusivo. Demografia usa `last_30_days`,
período lifetime e um breakdown por chamada. Account insights fazem UPSERT pela chave
`(account_id, period_start, period_end)` e demografia por
`(account_id, snapshot_date, audience_type, breakdown_type, breakdown_value)`. Recoletas
atualizam os valores e `collected_at` da linha existente, preservando períodos/dias anteriores.
`reposts` é tentada como métrica opcional da conta; ausência/incompatibilidade gera NULL e warning.
`instagram_media_insights` continua preservando todos os snapshots intradiários.
Mídias representam contadores acumulados no instante
da consulta. Insights e URLs podem ser recalculados/expirar na Meta; não são cópias dos arquivos.

```sh
python -m alembic upgrade head
python -m alembic current
python -m alembic check
python -m alembic upgrade head --sql
# Operação destrutiva: remove tabelas e histórico. Apenas para banco de testes descartável:
python -m alembic downgrade base
```

No Compose, prefira `docker compose exec instagram-bi python -m alembic current` e `check`.
No Dokploy, esses comandos podem ser executados no terminal do container. Migrations online
leem configuração do ambiente; geração offline de SQL não precisa de token ou banco.

A migration incremental `0002_bi_data_integrity.py` atualiza bancos já na revisão `0001_initial`.
Antes das constraints, mantém a linha com `collected_at` mais recente para cada chave de conta
ou demografia (maior ID em caso de empate) e remove somente suas duplicidades. Não soma
métricas nem altera linhas de `instagram_media_insights`. O downgrade restaura o schema e
as views anteriores; não recupera as duplicidades removidas nem os valores da coluna reposts.

## 10. Jobs, resiliência e auditoria

- **account (todos os dias às 07:00):** perfil/counters → snapshot diário → insights do dia anterior → demografia.
- **media (00:00, 06:00, 12:00 e 18:00):** `/me/media` com paginação completa → upsert de todas as publicações disponíveis
  → insights para mídias publicadas nos últimos 90 dias, por default.
- **all:** agenda account e media em sequência; retorna os dois IDs. O segundo registro fica
  RUNNING enquanto aguarda o primeiro.

Os horários seguem `TIMEZONE=America/Cuiaba`. O scheduler usa cron, portanto reiniciar o
processo mantém os próximos horários do calendário. As variáveis `ACCOUNT_COLLECTION_HOURS`
e `MEDIA_COLLECTION_HOURS` foram substituídas pelas configurações cron da seção 5; atualize
o ambiente do Dokploy e faça redeploy. A coleta inicial continua independente da agenda:
`COLLECT_ON_STARTUP=true` executa account e media a cada inicialização. Para executar apenas
nos horários agendados, configure `COLLECT_ON_STARTUP=false`. Os endpoints manuais também
continuam disponíveis fora desses horários.

Um lock `GET_LOCK` no MySQL evita overlap entre processos usando o mesmo database. Uma
chamada manual concorrente recebe 409. Se um horário agendado disparar enquanto outra coleta
está ativa, aquele job é pulado e uma mensagem INFO é registrada.

### Aplicabilidade de métricas e warnings

A matriz abaixo incorpora a validação empírica informada para a conta monitorada:

| Produto/tipo | Métricas comuns | follows/profile_visits | Watch time/skip rate |
|---|---|---|---|
| FEED — IMAGE/CAROUSEL_ALBUM | views, reach, likes, comments, shares, saved, total_interactions | Consultadas | NOT_APPLICABLE |
| REELS | views, reach, likes, comments, shares, saved, total_interactions | NOT_APPLICABLE | Consultadas |

Métricas NOT_APPLICABLE não geram chamada HTTP nem warning, ficam NULL no snapshot e
podem ser vistas nos logs DEBUG. A seleção está centralizada em `collectors/metrics.py`.
Outros tipos continuam usando a estratégia resiliente existente.

No nível da conta, `profile_visits` continua sendo tentada: erro explícito de métrica
incompatível ou `data: []` é classificado como opcional/UNSUPPORTED em DEBUG, sem incrementar
`warnings_count`. Se um valor válido for retornado, ele é armazenado. Respostas inesperadas,
JSON de dados malformado e falha de parsing continuam gerando warning. Falhas OAuth, de
permissão, rate limit e infraestrutura continuam sendo tratadas como erros relevantes.
`follows_and_unfollows` permanece na coleta e mantém warning quando seu breakdown não é
reconhecido pelo parser. Não há mudança no schema nem necessidade de nova migration.

Retries: timeout, transport errors, HTTP 429/5xx, rate-limit codes e erros marcados pela Meta
como transitórios; backoff de 2/4/8s com três retries, respeitando `Retry-After` maior. OAuth/token
expirado e outros 4xx permanentes não são repetidos. Erros de métrica/campo inválido são
warnings, exceto indisponibilidades esperadas descritas acima; JSON sem métrica ou sem valor
numérico gera NULL. Uma permissão inválida global
não é confundida com métrica incompatível. Falhas permanentes de uma mídia são auditadas
e permitem processar as próximas; timeout/rate limit esgotado encerra o job, preservando
commits já realizados. Demografia é opcional e sua falha não invalida snapshots principais.

`etl_runs` usa RUNNING, SUCCESS, SUCCESS_WITH_WARNINGS ou FAILED. Contadores são finalizados
ao terminar. `records_read` conta objetos de perfil/mídia recebidos; inserted/updated contam
linhas persistidas, incluindo snapshots/demografia, portanto não precisam somar ao read.
Warnings incluem ausência/incompatibilidade inesperada; errors incluem falhas de objetos/jobs. As
mensagens de erro persistidas são diagnósticos sanitizados, sem payload bruto ou token.

Coletas incompletas permanecem visíveis na auditoria. Após interrupção abrupta, registros
RUNNING abandonados são marcados FAILED na próxima aquisição do lock. Shutdown normal
cancela a coleta e finaliza a auditoria. Commits incrementais conservam os dados anteriores
se houver falha em página posterior. Nenhum snapshot é apagado por um job de coleta.

## 11. Endpoints

| Método/rota | Autenticação | Resultado |
|---|---|---|
| `GET /health` | sem chave | 200 `{status: ok, database: ok}`; 503 quando DB indisponível |
| `GET /api/status` | sem chave | últimos jobs, total contas/mídias, última conclusão bem-sucedida |
| `POST /api/jobs/account` | `X-API-Key` | 202 e `run_ids` |
| `POST /api/jobs/media` | `X-API-Key` | 202 e `run_ids` |
| `POST /api/jobs/all` | `X-API-Key` | 202 e dois `run_ids` |

Chave ausente/incorreta: 401; job já ativo: 409; falha interna: 500 com mensagem fixa.
As rotas não retornam configuração ou token. A chave não é aceita por query string.
Documentação interativa: `http://localhost:8000/docs`.

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/api/status
# ADMIN_API_KEY já configurada na sessão; não copie secrets para URLs:
Invoke-RestMethod -Method Post http://localhost:8000/api/jobs/all `
  -Headers @{ 'X-API-Key' = $env:ADMIN_API_KEY }
```

## 12. Testes

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
python -m compileall -q app alembic
docker build -t instagram-bi:local .
```

Os testes usam HTTPX MockTransport e SQLite em memória, com credenciais fictícias definidas
nas fixtures, sem chamar a Meta. Cobrem paginação/token somente no header, retries, parsers,
métrica inválida/ausente, follows/unfollows, delta diário, upsert, múltiplos snapshots, lookback,
auditoria, cancelamento, auth HTTP, secrets mascarados, UTC, upgrade/downgrade, comparação
schema/models e views com divisão por zero. A geração de DDL também é testada para MySQL.
Os testes do scheduler verificam horários cron no fuso de Cuiabá, virada do dia, configuração
por ambiente e rejeição de horas/minutos inválidos.

O relatório [VALIDATION.md](VALIDATION.md) registra **94 testes aprovados e 2 integrações
MySQL puladas** na revisão do agendamento de 07/10/2026, com Ruff e Docker build aprovados.
A validação anterior de 06/10 registra **80 testes aprovados com MySQL 8.4** e
**78 aprovados/2 integrações puladas na imagem Python 3.12**, incluindo aplicabilidade de
métricas, UPSERTs, migration incremental de bases com duplicidades e views. SQLite
não substitui a validação MySQL de DDL, locks e views. Antes de produção valide as respostas
reais da conta, escopos, disponibilidade/latência e semântica das métricas com a versão configurada.

## 13. Power BI

1. Instale o conector/driver MySQL exigido pela sua versão do Power BI Desktop.
2. No MySQL, crie um usuário dedicado a BI e conceda somente SELECT ao schema de analytics:

   ```sql
   CREATE USER 'powerbi'@'%' IDENTIFIED BY '<senha-exclusiva-bi>';
   GRANT SELECT ON instagram_bi.* TO 'powerbi'@'%';
   ```

   Restrinja o host/permissão à rede real do BI em produção.
3. Power BI → Obter dados → Banco de dados MySQL → servidor/porta e `instagram_bi`.
4. Importe as views abaixo e, para crescimento, a tabela histórica de media insights.
5. Para Power BI Service, configure gateway de dados quando o MySQL estiver em rede privada.

| View | Conteúdo |
|---|---|
| `vw_instagram_account_daily` | date, ID/username, seguidores/delta, follows_count, media_count |
| `vw_instagram_account_insights` | Uma linha por conta/período, incluindo reposts |
| `vw_instagram_audience_demographics` | Buckets diários com data, ID/username, audiência, breakdown, valor e coleta |
| `vw_instagram_media` | Metadados e contadores atuais da publicação |
| `vw_instagram_media_latest_insights` | Exatamente um insight mais recente por media_id |
| `vw_instagram_media_performance` | Mídia + último insight + taxas + follows, profile_visits, watch times e skip_rate |

As taxas usam `numerador / NULLIF(reach, 0) * 100`, retornando NULL quando reach é zero ou
ausente. `LEFT JOIN` conserva mídias ainda sem insights. A view latest ordena por collected_at
e id, garantindo seleção determinística. Use a tabela `instagram_media_insights` para calcular
diferenças entre snapshots e crescimento em 24h/3/7 dias; as views não substituem o histórico.
Para relacionamentos de tabelas, `instagram_media.id → instagram_media_insights.media_id`
e `instagram_accounts.id → account_id`. Timestamps estão em UTC; converta explicitamente no BI.

O primeiro snapshot começa no dia da instalação. A API não fornece por este fluxo o histórico
intradiário anterior à implantação; não é possível reconstruí-lo a partir do total atual.

## 14. Troubleshooting

| Sintoma | Verificação |
|---|---|
| Falha de configuração no boot | Secrets não vazios, porta, timezone, horas 0–23 e minutos 0–59 |
| Database unavailable/migration failed | Host/porta, banco criado, usuário, grants DDL e migrations |
| Health ok, job FAILED por OAuth | Token expirado/revogado, app/conta corretos; rotacione no ambiente |
| Métrica NULL com warning | Tipo de mídia, versão, permissão, idade e tamanho da audiência |
| Follows/unfollows NULL | Breakdown ausente ou labels desconhecidos; não use delta como fallback |
| Insights atrasados | Aguarde atualização da Meta; snapshots refletem o valor retornado |
| Menos mídias que esperado | API só entrega objetos acessíveis ao token; coleção não recupera removidos |
| Stories ausentes | `/me/media` não garante Stories; suporte é para tipos efetivamente retornados |
| Job media longo/rate limit | Configure menos horários/reduza lookback; métrica individual aumenta chamadas |
| 409 em chamada manual | Outra coleta detém o lock; consulte status e aguarde conclusão |
| RUNNING após crash | Próxima coleta recupera auditoria; verifique disponibilidade do banco |
| Dados antigos sem novos insights | Metadados preservados; idade acima do lookback configurado |
| Power BI sem acesso | Driver, gateway, firewall, DNS e usuário SELECT |
| Docker build falha antes do build | Docker engine ativo e permissão de acesso ao Docker Desktop |

Não habilite dumps de headers/responses, logs SQL com parâmetros nem access logs que gravem
URLs brutas. Nunca registre `.env`, token, app secret, senha MySQL ou ADMIN_API_KEY. O token
não tem coluna no banco e não é incluído em erros HTTP nem mensagens ETL. A aplicação
não baixa imagens/vídeos e não depende de arquivos persistentes fora do MySQL.

## Árvore de arquivos

```text
app/
  main.py, config.py, entrypoint.py
  api/                 routes_health.py, routes_jobs.py
  clients/             instagram_client.py
  collectors/          account_collector.py, account_insights_collector.py
                       media_collector.py, media_insights_collector.py
                       insights_parser.py, metrics.py
  database/            base.py, session.py
  models/              instagram_account.py, instagram_account_daily.py
                       instagram_account_insights.py, instagram_media.py
                       instagram_media_insights.py, instagram_audience.py, etl_run.py
  schemas/             jobs.py
  services/            instagram_service.py, scheduler_service.py, token_service.py
  utils/               dates.py, logging.py, retry.py
alembic/
  env.py, script.py.mako
  versions/0001_initial.py, 0002_bi_data_integrity.py
tests/
  conftest.py, test_api.py, test_bi_integrity.py, test_client.py, test_insights.py
  test_migrations.py, test_mysql_integration.py, test_security.py
  test_service.py, test_storage.py, test_metric_applicability.py, smoke_container.py
.env.example, .gitignore, .dockerignore
Dockerfile, docker-compose.yml, alembic.ini
requirements.txt, requirements-dev.txt, pyproject.toml
README.md, VALIDATION.md
```
