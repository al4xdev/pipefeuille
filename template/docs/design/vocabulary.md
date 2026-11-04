# Vocabulário do projeto

Nomes recorrentes e seus limites. Esta página registra significados; não cria fases obrigatórias. Usar um nome no código não o promove a padrão: só o dono do projeto move uma proposta para "Definidos".

## Definidos pelo dono

Os seis nomes que o dono do Tavern definiu; o dono deste projeto os herda como ponto de partida.

| Nome | Significado | Limite |
| --- | --- | --- |
| `run.py` / `run` | Entrada pública e composição completa do nível (`def` ou `async def`). | Não é reexport. |
| `Pipe` | Objeto fluente local de um pacote. | Sempre `Pipe`; o pacote dá o domínio. |
| `get(initial)` | Factory com a preparação inicial. | Não é getter. Aliases `have`/`start`/`create` proibidos. |
| `Container` | Dataclass tipada do estado intermediário, forma fixa, vazios declarados (`None` inicial é legítimo; vazio tipado também). | Não é DTO, prompt nem schema persistido. |
| `self.container` | Único lugar dos intermediários. | `self.context`/`self.state` proibidos. |
| `materialize` | Terminal que devolve a saída tipada. | `result`/`build`/`finish` proibidos. |

## Herdados do Alex Tavern (propostas aceitas como ponto de partida)

Verbos (os cinco propostos pelo coordenador do Tavern): `validate_*`, `prepare_*`, `project_*`, `admit_*`, `commit` — significados na §3.3 do guia. Outros nomes de método (`resolve_*`, `read_*`, `decode_*`, `publish_*`…) são nomes locais legíveis, não vocabulário.

Sufixos: `*Definition`, `*Candidate`/`Proposed*`, `Admitted*`/`Checked*`, `*Draft`, `*View`, `*Document`, `*Receipt`, `*State`, `*Entity`, `*Error`/`*ResultError` — significados na §3.4 do guia. O `Input`/`Output` genérico do Tavern foi substituído neste template por pedidos nomeados (abaixo).

Leitura: `None` no Container = etapa não executada; `Missing` = ausência observada; `Found` = leitura concluída.

## Convenções do template (não herdadas)

| Convenção | Limite |
| --- | --- |
| Filho chamado pelo módulo com alias: `lazy from .encode import run as encoding` → `encoding.run(...)` | No Tavern o alias varia (`as authorizing`, `as select_provider`, `as evidence`); não há regra de gerúndio. |
| Docstring `Require …; set …; efeitos; falhas` | A exigência é semântica (lido/exigido/escrito/preservado/efeitos); a frase é estilo. |
| Cinco arquivos obrigatórios em toda pasta de `backend_logic` (`__init__`, `contracts`, `container`, `pipeline`, `run`) e nenhum outro nome de módulo | Decisão do dono, mais estrita que o Tavern. Legibilidade: qualquer leitor sabe onde o pacote roda (`run.py`, `def run`) sem conhecer o domínio. |
| Pedido nomeado `<Verbo><Objeto>` (`SaveNote`, `ListNotes`, `DecodeText`, `WriteDocument`) e produto nomeado (`SavedNote`, `NoteNames`, `WriteReceipt`) | Substitui `Input`/`Output`. O tipo mora no pacote que o atende. |
| Família: `type <Família>Request = A \| B` no `contracts.py` e `match` visível no `run.py`, com `@overload` por caso | A raiz `backend_logic/` é família; todo ancestral de família também é. Filhos de um processo (`save/decode`) são etapas, não casos. Família importa contratos dos filhos; filho nunca importa a família. |
| `Validated(value)` no Container da família | Embrulha um produto que pode ser `None` (JSON `null`) para não se confundir com "ramo não rodou". |
| Mecanismo como um pacote por operação: `json/{validate,decode,encode}`, `storage/{path,read,write,scan,lock}` | No Tavern, `JsonValue`/`json.loads` e a escrita vivem em `storage/files.py`. Aqui cada operação tem nome legível e os cinco arquivos; `json/` é irmão de `storage/` na raiz porque storage, papéis LLM e a borda HTTP o usam. Política JSON estrita: duplicatas, NaN, surrogates, profundidade → `ValueError`. |
| Frontend entra só por `backend_logic/run.py` e importa só módulos `contracts` | Recursos preparados no `lifespan` por `backend.run(PrepareResources(...))`, guardados num `ResourceSlot` do frontend. Corpo HTTP pela família JSON, sem pydantic (escolha de gate; o Tavern não impõe estilo ao frontend). |
| Autoridade compartilhada como pacote irmão (`notes/name/`) | Mesma forma de `catalog/presets/name/` no Tavern. Toda fronteira que recebe um nome — input, documento lido, arquivo listado — passa por ela; rejeição de dado lido é corrupção (`ValueError`), não erro do cliente. |
| Código de erro e fase como `type <X>Code = Literal[...]` / `type <X>Phase = Literal[...]` no `contracts.py` do dono do erro (`NoteConflictCode`, `NoteValidationCode`, `WritePhase`) | Conjunto fechado: código mostrado ao cliente é contrato, e um código novo muda o tipo. Gate em `tests/test_style.py` proíbe `code`/`phase` anotados como `str` em `backend_logic`. |
| Número com papel próprio como `NewType` (`Revision`) | Construir não valida; a etapa que admite constrói (`Revision(current.revision + 1)`). Orçamentos de chamada (`max_*`, `output_tokens`) ficam `int` com nome no parâmetro, para o `run` seguir legível. |
| Regras de vocabulário verificadas por `tests/test_style.py` | O teste só garante o que é mecânico; a semântica (o que cada `validate_*` verifica de fato) continua sendo revisão. |

## Propostas em observação

| Nome | Onde apareceu | Significado proposto | Limite / dúvida |
| --- | --- | --- | --- |
| `Resources` | `backend_logic/runtime/application` | Recursos de lifetime da aplicação com um dono. | Não é sessão nem request container; não acumula métodos. |
| `require_object` | `notes/save/decode` | Exigir objeto JSON com chaves exatas. | Shape, não admissão semântica. |

<!-- Ao adicionar: nome, onde apareceu, significado, o que NÃO significa. -->