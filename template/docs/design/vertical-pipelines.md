# Guia de referência: pipelines verticais, legibilidade primeiro

> O código é o próprio blueprint. O esqueleto precisa ser tipado e **ensaiado**, não apenas existir. Cada pacote conta uma história completa no seu nível; as transformações trabalham em um `Container` local até `materialize` entregar a saída.

Derivado do Alex Tavern 2 (guia111 revisão6, vocabulário e lições de processo). Este é o núcleo transferível: vale para qualquer projeto de agentes que nasça neste estilo. O que é específico do Tavern (roleplay, reconstrução de um app antigo, provider preferido) está separado na seção 18.

**Autoridade da fonte:** o Tavern está inacabado (há stubs e pacotes a meio caminho). Os documentos de design dele (`vertical-pipelines.md`, `vocabulary.md`, `AGENTS.md`) definem o padrão. O código dele serve só como exemplo: variação no código, ou ausência de algo nele, não autoriza desvio do padrão. Quando este guia cita código do Tavern, é para ilustrar, não para criar regra.

Antes de mexer num pacote, leia este guia e o [vocabulário](vocabulary.md) do projeto. O resumo em `AGENTS.md` não é uma arquitetura concorrente; em conflito, este guia vale.

---

## 1. Princípios em uma linha

1. **O código é o blueprint.** Pacotes, tipos, Containers, assinaturas e composições reais vêm antes da lógica. Árvore em Markdown não substitui código.
2. **Ler de cima para baixo como uma conta.** Legibilidade vence DRY mecânico, funções curtas e poucos parâmetros.
3. **Tipagem estrita delimita a liberdade do implementador.** Quanto mais o contrato diz, menos o agente adivinha.
4. **Ensaiar antes de delegar.** O esqueleto roda com fakes tipados e dados coerentes atravessando as ligações reais.
5. **Pacotes verticais completos, em qualquer profundidade útil.** Cada `run` conta a história inteira do seu nível.
6. **Ordem fixa e visível.** Nada de motor de steps, DSL de orquestração ou fila escondida de efeitos.
7. **Estado explícito.** Configuração e recursos são carregados pelo dono e passados como argumento; nada de `CLIENT`/`STATE`/`SETTINGS` global.
8. **Honestidade de status.** Tipagem verde, testes verdes e mocks não provam produto pronto. Diga o que está ausente, ensaiado, implementado, integrado e verificado.

Não se aplica Clean Code, Clean Architecture, DRY ou imutabilidade por obrigação. Uma função longa e coerente, composição repetida, literal no parâmetro ou argumento que "poderia ser buscado internamente" podem ser escolhas deliberadas de leitura.

---

## 2. Anatomia de um pacote

```text
notes/save/
├── __init__.py     # docstring de uma linha; nenhum I/O, config ou startup no import
├── contracts.py    # tipos que entram e saem, tipos dos campos do Container, portas, erros
├── container.py    # @dataclass Container: forma fixa, campos vazios declarados (None ou vazio tipado)
├── pipeline.py     # class Pipe: get(), transformações que retornam Self, materialize()
├── run.py          # def run / async def run: a composição visível, entrada pública
└── encode/         # filho: outro pacote completo, com seu próprio Container
    ├── __init__.py
    ├── contracts.py
    ├── container.py
    ├── pipeline.py
    └── run.py
```

| Arquivo | Papel | Não é |
| --- | --- | --- |
| `run.py` | Onde o pacote roda: `def run` é a entrada pública e a composição completa daquele nível. Comece a ler sempre por ele. | Reexport de outro módulo. Todo `run.py` define um `run` real (teste de arquitetura garante). |
| `contracts.py` | Os tipos que o pacote troca e guarda: o pedido que entra (`SaveNote`), o produto que sai (`SavedNote`), os tipos dos campos do Container e das mutações (`CurrentRead`, `NoteDocument`), `Protocol`s de portas e erros. Cada tipo mora no pacote que o produz ou admite (`NoteName` em `notes/name/`, `NoteRecord` em `notes/save/`). | DTO HTTP, saco de tipos do projeto inteiro, lugar de lógica. |
| `container.py` | Estado local fixo, preenchido progressivamente. Também é a fronteira para fixtures de "começar no meio". | Configuração, megacontexto, DTO público. |
| `pipeline.py` | `Pipe` e seus métodos de transformação. | Lugar para esconder a sequência; a ordem fica em `run`. |
| `__init__.py` | Identifica o pacote. | Lugar de startup, leitura de config, conexão ou plugin. |

**Os cinco nomes são obrigatórios em toda pasta de `backend_logic`, e nenhum outro nome de módulo existe** (decisão do dono deste template, mais estrita que o Tavern, que tolera módulos soltos para tipos e mecanismos). A razão é legibilidade: quem abre uma pasta sem saber nada do domínio — o que é `codec`? o que faz `jsonvalue`? — ainda sabe onde começar (`run.py`, `def run`), o que o pacote guarda (`container.py`) e o que ele troca (`contracts.py`). Um mecanismo compartilhado não vira módulo solto (`files.py`, `locks.py`, `jsonvalue.py`): vira um pacote por operação, com nome legível (`storage/write/`, `storage/lock/`, `json/decode/`). `tests/test_style.py` garante os cinco arquivos e a ausência de qualquer outro.

**Cada pasta é um pacote; a profundidade diz quem compartilha.** A árvore é a arquitetura. Cada pasta é um pacote completo com seu `run`, e o **lugar** dela na árvore declara quem a usa:

- Usado por um único pacote: fica **dentro** dele, na profundidade máxima.
- Usado por pacotes irmãos: sobe para o **pai comum** e fica no mesmo nível que eles, como mais um irmão.
- Usado por famílias distantes: sobe até o menor ancestral comum — nunca direto à raiz "por precaução".

```text
backend_logic/
├── run.py              # a porta única: match sobre BackendRequest → família
├── contracts.py        # BackendRequest = RuntimeRequest | NotesRequest | RolesRequest | JsonRequest
├── runtime/            # família: recursos de lifetime
│   └── application/
├── json/               # família: storage, roles e a borda HTTP a usam → raiz
│   ├── validate/       # decode e encode o usam → nível deles
│   ├── decode/
│   └── encode/
├── storage/            # família: toda família que persiste → raiz
│   ├── path/           # read, write e scan o usam → nível deles
│   ├── read/
│   ├── write/
│   ├── scan/
│   └── lock/
├── notes/              # família: run.py faz match sobre ListNotes | SaveNote
│   ├── name/           # autoridade do nome: list, save e save/decode → nível de notes
│   ├── list/
│   └── save/
│       ├── decode/     # só save lê o documento antigo → dentro de save
│       └── encode/     # só save escreve → dentro de save
└── roles/              # família: papéis LLM
    └── summarizer/
```

Ler o caminho de import já conta a história: `from .encode import run` é "meu filho"; `from ..name import run` é "um irmão que a família compartilha". Quando um segundo consumidor real aparece, o pacote **sobe** um nível e os imports dos dois são atualizados juntos; quando o último consumidor some, ele **desce** de volta. No Tavern, `catalog/presets/name/` é usado por `read`, `save`, `delete`, `avatar` e `list/entry`, e por isso mora ao lado deles.

**A subida: família e processo.** Há dois tipos de pacote, e o `contracts.py` diz qual é:

- **Família** declara `type <Família>Request = A | B` (ex.: `NotesRequest = ListNotes | SaveNote`). O `run.py` dela recebe o pedido tipado e um `match` visível desce ao filho que o atende. A raiz `backend_logic/` é uma família, e todo ancestral de uma família também é, então a leitura de qualquer caso de uso começa em `backend_logic/run.py` e desce `match` a `match` até uma folha.
- **Processo** tem uma cadeia de etapas no `run.py`. Filhos de um processo (`save/decode`, `save/encode`) são etapas dele, não casos de uso, e não precisam de `match`.

```python
# backend_logic/notes/run.py
async def run(
    initial: NotesRequest, *, store: FileStore, locks: LockRegistry, clock: Clock
) -> NotesResponse:
    pipe = Pipe.get(initial)
    match initial:
        case ListNotes():
            pipe.list_notes(initial, store=store)
        case SaveNote():
            await pipe.save_note(initial, store=store, locks=locks, clock=clock)
        case _:
            assert_never(initial)
    return pipe.materialize()
```

Cada caso chama um método do `Pipe` da família que delega ao `run` do filho e grava o produto no Container; `@overload` no `run` dá a quem chama o tipo exato de cada caso. O `contracts.py` da família só importa os contratos dos filhos, e os filhos nunca importam o da família: assim não há ciclo. Quando um produto legítimo pode ser `None` (JSON `null`), o Container o guarda embrulhado (`Validated(value)`), para que "o ramo rodou e devolveu `None`" não se confunda com "o ramo não rodou".

### 2.1. Exemplo mínimo completo

`contracts.py`

```python
@dataclass(frozen=True)
class ListNotes:
    """List every stored note name. No client input: the directory is server-owned."""


@dataclass(frozen=True)
class NoteNames:
    """Sorted, admitted note names without the JSON suffix; no document contents."""

    names: tuple[NoteName, ...]
```

`container.py`

```python
@dataclass
class Container:
    input: ListNotes | None = None
    files: tuple[str, ...] | None = None
    stems: tuple[str, ...] | None = None  # candidates, not yet admitted
    names: tuple[NoteName, ...] | None = None  # admitted by notes/name
```

`pipeline.py`

```python
class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: ListNotes) -> Self:
        """Set input unchanged; the directory is chosen by run, not by the caller."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def scan_directory(self, *, store: FileStore, relative: str) -> Self:
        """Set files directly beneath relative through storage. Read-only I/O."""
        self.container.files = storing.run(ScanDirectory(store, relative))
        return self

    def admit_names(self) -> Self:
        """Require stems; set names admitted by the shared notes/name authority. No I/O."""
        ...
        self.container.names = tuple(naming.run(stem) for stem in stems)
        return self

    def materialize(self) -> NoteNames:
        """Require completed names, including a legitimately empty tuple; return NoteNames."""
        names = self.container.names
        if names is None:
            raise RuntimeError("note names are required")
        return NoteNames(names=names)
```

`run.py`

```python
def run(initial: ListNotes, *, store: FileStore) -> NoteNames:
    return (
        Pipe
            .get(initial)
                .scan_directory(store=store, relative="notes")
                    .select_stems(suffix=".json")
                        .admit_names()
                            .sort_names()
                                .materialize()
    )
```

O template em `backend_logic/notes/` contém este exemplo completo, o irmão compartilhado `name/`, um processo assíncrono com filhos, lock, commit e recibo (`save/`) e a família que despacha entre eles (`notes/run.py`). O confinamento de caminho e o I/O não ficam em `list`: são de `storage/path` e `storage/scan`, chamados por `storing.run(ScanDirectory(...))`.

---

## 3. Vocabulário canônico

### 3.1. Nomes definidos (não variar)

| Nome | Significado único |
| --- | --- |
| `run.py` / `run(...)` | Entrada pública e composição completa do nível, inclusive `async def run`. |
| `Pipe` | Objeto fluente local. Sempre se chama `Pipe`; o pacote dá o domínio. |
| `get(initial)` | Factory com a preparação inicial declarada. Lê-se "o processo **recebe** tal coisa". Não é getter de propriedade. |
| `Container` | Dataclass tipada, forma fixa, preenchimento progressivo. |
| `self.container` | Único lugar dos intermediários. Nada de `self.prompt`, `self.response` soltos. |
| Métodos fluentes | Transformam o container e retornam `Self`. |
| `materialize(...)` | Terminal: devolve a saída tipada, não `self` nem o container inteiro. |

**Proibido:** aliases que dividam a linguagem — `have`/`start`/`create` no lugar de `get`; `result`/`build`/`finish` no lugar de `materialize`; `self.context`/`self.state` no lugar de `self.container`. Um tipo de domínio chamado `CallResult` é permitido: nome de tipo não é método terminal.

### 3.2. Chamando um filho

O pai importa o `run` do filho com um alias que nomeia a ação ou o produto daquele processo. No Tavern a forma varia — `run as exchanging`, `run as authorizing`, mas também `run as select_provider`, `run as estimate_prompt`, `run as evidence` — então **não há regra de gerúndio**; o template usa o módulo com alias (`encoding.run(...)`) por legibilidade:

```python
lazy from .encode import run as encoding  # template (lazy: §6.1)
from ..credentials.resolve import run as authorizing  # Tavern, módulo
from ..estimate.run import run as estimate_prompt  # Tavern, função

...
self.container.document = encoding.run(self.container.record)
```

O que importa: fica visível na leitura que ali começa outro processo completo, com seu próprio Container, e o pai importa `run`/`contracts` do filho, nunca `pipeline` ou helpers internos.

### 3.3. Verbos com significado consistente

Não são fases obrigatórias. O vocabulário do Tavern tem só **cinco** verbos propostos pelo coordenador (`validate_*`, `prepare_*`, `project_*`, `admit_*`, `commit`); quando aparecem, significam isto:

| Verbo | Significa | Não significa |
| --- | --- | --- |
| `validate_*` | Verificar um contrato e falhar explicitamente. | Corrigir, completar ou inventar valores. |
| `prepare_*` | Preparar valor/recurso usado depois. | Ausência de I/O — declarar efeitos na docstring. |
| `project_*` | Construir visão delimitada de dados existentes. | Ampliar audiência ou transformar opinião em fato. |
| `admit_*` | Aceitar uma proposta conforme a autoridade daquele domínio. | Parsing; e diferente de `commit`. |
| `commit` | Publicar uma mudança canônica **uma vez**, guardando um recibo/resultado explícito. | Atualizar um campo local; nem rótulo genérico para rede ou inferência. |

Todo o resto são **nomes locais legíveis**, não vocabulário: `resolve_directory`, `read_entries`, `select_names`, `sort_names` (o próprio Tavern diz que "não viraram um framework universal"), e efeitos com nome de domínio como `open_response`, `capture_response`, `publish_checkpoint`, `publish_state`. Neste template, `resolve_path`, `read_current`, `decode_reply`, `encode_record` são do mesmo tipo. Se um deles se repetir com o mesmo significado em vários pacotes, proponha-o em `vocabulary.md`.

### 3.4. Sufixos de tipo (usar só quando o significado existe)

| Sufixo | Significado | Exemplo |
| --- | --- | --- |
| `<Verbo><Objeto>` (pedido) / `<Família>Request` | Caso de uso tipado que entra num `run`, nomeado pelo que pede; a família une os pedidos dos filhos numa `type <Família>Request = A \| B`. Substitui o `Input`/`Output` genérico: o nome do pedido é legível fora do pacote. | `SaveNote`, `ListNotes`, `NotesRequest` |
| `*Definition` | Configuração autoral ainda não materializada. | `ScenarioDefinition` |
| `*Candidate` / `Proposed*` | Dado ainda **não admitido**. | `UpdateCandidate`, `ProposedEvent` |
| `Admitted*` / `Checked*` | Marca a conclusão de uma admissão/checagem específica. | `AdmittedSchema`, `CheckedSubmission` |
| `*Draft` | Cópia isolada a mutar antes do commit. | `UndoDraft`, `InputDraft` |
| `*View` | Visão projetada para um consumidor (dono, leitor). | `PresetView` |
| `*Document` | Forma serializada na fronteira externa. | `PrivateConfigDocument` |
| `*Receipt` | Evidência do resultado de um efeito — **não** implica sucesso ou durabilidade. | `WriteReceipt` |
| `*State` | Estado canônico ou vocabulário fechado do domínio. | `SessionState` |
| `*Entity` | Entidade canônica tipada por espécie (união discriminada). | `ActorEntity` |
| `*Error` / `*ResultError` | Falha. `*ResultError` = falha terminal **depois de trabalho concluído**, que não autoriza retry/replay: preserva o recibo quando houve publicação (`PresetResultError`) ou marca falha interna não-retentável sem recibo (`ValueResultError`, `CaptureResultError`). | `PresetResultError`, `ValueResultError` |

Estados de leitura que não se confundem: `None` no Container = **etapa não executada**; `Missing` = ausência observada; `Found` = leitura concluída (mesmo que o conteúdo seja `null`). Para etapas: `stage` = tentativa atual; `completed_stage` = chamada que retornou.

Identidades nominais (`NewType`) distinguem valores que não podem ser trocados (`ActorId` ≠ `SessionId`), mas construir um `NewType` **não valida nada**; a validação é uma etapa própria.

### 3.5. Docstring de método = contrato local

A exigência é **semântica**: cada método declara campos lidos, exigidos, escritos e preservados, e seus efeitos e falhas. O guia do Tavern escreve isso em prosa livre ("Lê input; preenche prompt; não faz I/O…"). Métodos sem docstring no código do Tavern não são precedente: a fonte está inacabada. Este template usa uma fraseologia curta em inglês, que é **escolha do template**, não fórmula obrigatória:

```python
def read_current(self, *, store: FileStore) -> Self:
    """Require name and builtin protection; set current_read. Read-only I/O; no publication."""


def commit(self, *, store: FileStore) -> Self:
    """Require path/document and named lock; publish once and retain WriteReceipt.

    Propagate AtomicWriteError unchanged. No retry.
    """
```

`Require …` (campos lidos/exigidos) · `set …` (campos escritos) · efeitos permitidos/proibidos · falhas. `-> Self` sozinho não é contrato: os campos do Container também são entradas e saídas.

### 3.6. Novos nomes

Nome recorrente novo vai para `docs/design/vocabulary.md` na seção de **propostas**, com significado e limite. Só o dono do projeto promove uma proposta a nome definido. Usar um nome no código não o torna padrão.

---

## 4. Composição no `run`

### 4.1. Indentação semântica

Aprofundar a indentação comunica sequência/dependência. O formatter achataria essa escada, então **o `pyproject.toml` do template exclui `backend_logic/**/run.py` do `ruff format`** (com `force-exclude = true`, para valer também quando um editor ou agente passa o caminho do arquivo). Nenhum `run.py` precisa de `# fmt: off`/`# fmt: on`, e `tests/test_style.py` proíbe esses escapes no `backend_logic`. O linter continua valendo no `run.py` (imports, tamanho de linha, nomes, bugs); quem escreve o `run` é responsável pela forma dele. Os trechos de `run` citados em `docs/**/*.md` ficam fora do formatter pelo mesmo motivo. Todo o resto do código segue o formatter.

### 4.2. Branches, loops e locks ficam no `run`

```python
async def run(
    initial: SaveNote, *, store: FileStore, locks: LockRegistry, clock: Clock
) -> SavedNote:
    pipe = (
        Pipe
            .get(initial)
                .validate_name()
                    .resolve_path(directory="notes", suffix=".json")
    )
    if pipe.container.name is None:
        raise RuntimeError("note save requires validated name before locking")
    async with storing.run(SelectLock(locks, kind="note", name=pipe.container.name)):
        pipe.read_current(store=store)
        if initial.replace:
            pipe.admit_replacement()
        else:
            pipe.admit_creation(initial_revision=1)
        (
            pipe
                .read_time(clock=clock)
                    .prepare_record(schema_version=1)
                        .encode_record()
                            .commit(store=store)
        )
        try:
            return pipe.materialize()
        except Exception as error:
            if pipe.container.receipt is None:
                raise
            raise NoteResultError(pipe.container.receipt) from error
```

Note: lock adquirido no `run`, não escondido num método; o ramo é um `if` legível; a falha após o commit vira `*ResultError` com o recibo, para ninguém refazer o trabalho já publicado.

### 4.3. Async

`def`/`async def` conforme o trabalho; awaits visíveis. Python não encadeia métodos sobre coroutine não aguardada, então **método async fica numa linha `await pipe.x()` própria**, e a escada recomeça em `pipe` logo abaixo (`backend_logic/roles/summarizer/run.py`):

```python
pipe = (
    Pipe
        .get(initial)
            .project_note()
                .prepare_prompt(language=initial.language)
                    .prepare_request(output_tokens=256, response_mode="structured")
)
await pipe.call(model=model)
return (
    pipe
        .decode_reply()
            .admit_summary(max_sentences=3)
                .materialize()
)
```

Encadear depois do `await` é Python válido (`(await pipe.call(model=model)).decode_reply()…`), mas **este template não usa** (escolha do template por legibilidade; o dono pode revê-la no `architecture-log.md`): com uma etapa async parece fluente; com duas vira `(await (await pipe.a()).b()).c()`, e o ponto de suspensão some no meio dos parênteses. Na linha própria, o `await` fica na mesma coluna do `async with` e dos `if` do `run`, onde quem lê procura o que pode ser interrompido — o que importa para locks e cancelamento. Coroutine-proxy ou metaclasse para manter a fluência continuam proibidos.

### 4.4. Paralelismo

Paralelo é o pai chamando **pacotes irmãos ao mesmo tempo** num `asyncio.TaskGroup`: cada `create_task` é o `run` de um pacote completo, com seu próprio Container. Nada de executor genérico de fases nem lista de callbacks — o grupo fica visível no `run` do pai, e cada ramo é um processo que se lê sozinho.

O mesmo vale para **fan-out sobre itens**: N chamadas do `run` de um pacote irmão, cada uma com seu Container. Exemplo real do template, `backend_logic/roles/digest/run.py` (um resumo por nota, testado em `tests/test_roles_digest.py`):

```python
async def run(initial: DigestNotes, *, model: Model) -> Digest:
    pipe = (
        Pipe
            .get(initial)
                .validate_notes(max_notes=8)
                    .prepare_requests()
    )
    if pipe.container.requests is None:
        raise RuntimeError("digest requires prepared requests before the parallel calls")
    # Failure policy: TaskGroup. The first rejected summary cancels the calls still running
    # and the whole digest fails as an ExceptionGroup; a partial digest is never returned.
    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(summarizing.run(request, model=model))
            for request in pipe.container.requests
        ]
    # After the barrier, in request order: the digest never depends on which call finished first.
    return (
        pipe
            .integrate_summaries(tuple(task.result() for task in tasks))
                .materialize()
    )
```

O orçamento (`max_notes=8`) é validado antes de qualquer chamada paga; nota duplicada é rejeitada, não deduplicada. O teste prova a concorrência de verdade: o fake só responde a primeira nota depois que a segunda termina, então uma versão sequencial travaria e estouraria o `asyncio.timeout`. O digest sai na ordem das notas, não na de conclusão. Uma rejeição cancela as chamadas pendentes, e quem chama trata o `ExceptionGroup` com `except*`.

Com ramos **diferentes**, o esqueleto é o mesmo, uma tarefa por ramo:

Alinhar operações comunica ramos do mesmo grupo paralelo **somente** quando a execução realmente os agenda assim. Whitespace não cria concorrência.

```python
lazy from .images import run as images
lazy from .optional import run as optional
lazy from .thumbnail import run as thumbnail


async def prepare_optional(source: Source) -> Optional:  # ramo sequencial dentro do grupo
    downloaded = await optional.run(source)
    return await thumbnail.run(downloaded)


async with asyncio.TaskGroup() as group:
    optional_task = group.create_task(prepare_optional(source))
    images_task = group.create_task(images.run(source))
# Integração depois da barreira, em ordem fixa — não pela ordem de conclusão.
pipe.container.optional = optional_task.result()
pipe.container.images = images_task.result()
```

- Os filhos recebem inputs explícitos e devolvem outputs; só o pai escreve no seu Container, e só depois da barreira.
- Independência é semântica, não só campos diferentes. Escritas exclusivas são permitidas; dois writers no mesmo estado canônico, não.
- Integrar resultados deterministicamente, não por ordem de conclusão.
- Cancelamento não desfaz efeitos externos nem vira sucesso.
- `TaskGroup`, `gather` e variantes têm políticas de falha diferentes: escolha e declare.

### 4.5. `materialize`

Fecha o processo. Pode executar trabalho explicitamente adiado quando esse é o contrato, mas o nome não prova que nada aconteceu antes nem autoriza fila escondida de efeitos. Repetir `materialize` não é automaticamente seguro: declarar consumo único quando houver inferência paga ou commit.

---

## 5. Container

- Constructor cria `self.container = Container()` de verdade, com campos vazios declarados. Nada de `dict`, `SimpleNamespace`, `kwargs` ou atributos dinâmicos.
- Forma fixa; valores progressivos. **`None` inicial é legítimo, não obrigatório**: acumuladores e fases usam vazio tipado (`attempt_count: int = 0`, `refresh_used: bool = False`, `authorizations: tuple[...] = ()`, `scope: Scope = "prepare"`). Cada método declara o que lê, exige, escreve e preserva.
- `get(initial)` pode fazer a preparação inicial declarada — copiar/destacar a entrada (`deepcopy`), inicializar acumuladores — mas não esconde carregamento global.
- Campo obrigatório ausente falha **explicitamente** (`if x is None: raise RuntimeError(...)`), nunca com `assert` — `python -O` remove asserts.
- Sem defaults inventados. Se `None` também é uma saída válida, distinguir de "etapa não executada" com um tipo próprio (`AvatarSelection(value=None)`, `Literal[True] | None`).
- Uma instância de `Pipe`/`Container` por invocação. Nunca compartilhar estado de request entre chamadas.
- `materialize` não expõe o container. Container não é DTO público, prompt nem schema persistido.

---

## 6. Tipagem estrita

Objetivo não é mypy verde: é **reduzir o que o implementador precisa adivinhar**.

- Proibido: `Any`, coleções sem parâmetro (`dict`, `list`), imports não tipados tratados como `Any`, `cast`/`# type: ignore` para esconder contrato incompleto.
- Não trocar `Any` por `object`/`dict[str, object]`/`JsonValue` em todo o domínio só para passar na regra.
- Usar dataclass, `TypedDict`, `Protocol`, uniões discriminadas, `Literal`, `Enum`, `NewType` quando expressarem distinções reais.
- Escolhas finitas conhecidas são `Literal`/`Enum`, não `str`.
  No template: códigos de erro mostrados ao cliente (`NoteConflictCode`, `NoteValidationCode`), a fase da escrita atômica (`WritePhase`) e o idioma do papel (`Language`). Um código novo vira mudança de contrato visível no tipo, e não uma string que alguém inventou num `raise`.
- Número com papel próprio é `NewType`, não `int`: `Revision` não se troca por `schema_version`, por contagem nem por tamanho. A etapa que admite o valor é a que o constrói (`Revision(current.revision + 1)`); o teste que precisa de um valor o escreve explicitamente (`Revision(1)`).
- Distinguir o que não pode ser confundido: identidade vs referência, proposta vs fato admitido, documento bruto vs objeto validado, ausência vs etapa não executada, resultado vs recibo de efeito.
- `dict` é legítimo para chaves dinâmicas, com chave e valor tipados. Registro de campos conhecidos declara os campos.
- **Dado não confiável é amplo só na fronteira de ingestão** (JSON recursivamente tipado, `bytes`). A admissão produz tipos específicos; a indeterminação não atravessa os pacotes. API de biblioteca que retorna `Any` ganha uma fronteira de contenção.
- A força do tipo corresponde ao conhecimento da etapa: input ainda sujeito a rejeição não é anotado como admitido.
- Tipos não provam intervalos, relações entre campos, privacidade ou ordem temporal: declarar pré-condições e validar em runtime.
- Nunca relaxar o gate (excluir módulo, desligar regra) para obter verde.

Configuração de referência (`pyproject.toml` do template): `mypy strict = true`, `disallow_any_explicit`, `disallow_any_unimported`, e `disallow_any_expr` nos pacotes onde for viável; Ruff com `E,F,I,N,W,UP,B,C4,SIM`.

### 6.1. Imports `lazy` (Python 3.15, PEP 810)

O template exige Python 3.15 por um motivo: `lazy import`. **Todo import de topo de módulo em `backend_logic` e `backend_frontend` é `lazy`**:

```python
lazy import asyncio
lazy from typing import Self

lazy from backend_logic.roles.summarizer import run as summarizing
lazy from .container import Container
```

O módulo só é carregado no primeiro uso do nome. Importar `backend_logic.run` não carrega `storage/write` nem `roles/digest` até um pedido passar por eles, então a startup carrega só o caminho que usa. A árvore de pacotes pode crescer sem que cada `contracts.py` puxe o projeto inteiro.

Regras da linguagem:

- `lazy` só vale no topo do módulo. Import dentro de função, classe ou `try` fica normal, e o gate não o cobra.
- `from __future__ import ...` e `import *` não podem ser lazy.
- **O erro muda de lugar.** Um módulo ausente, ou um efeito colateral de import, só aparece no primeiro uso, não ao abrir o arquivo. Por isso os testes que exercitam cada caminho (o `run` real de cada pacote) são o que garante que os imports resolvem.

**Fallback:** se um pacote não funcionar como lazy (registro em tempo de import, efeito colateral do qual o código depende, ferramenta que ainda não entende a sintaxe), troque o `lazy import` por `import` normal naquele ponto. O comportamento é o mesmo, só eager. Para o gate aceitar a troca:

1. registre o módulo em `EAGER_IMPORTS` (em `tests/test_style.py`) com o motivo;
2. registre a exceção no `architecture-log.md`.

Para voltar o projeto inteiro a eager, remova todos os `lazy `. O template foi verificado assim: mesmos testes verdes e mypy limpo. Nesta build do CPython, `-X lazy_imports` aceita só `all` e `normal` e não desliga o lazy explícito, então o fallback é mudar o código, não passar uma flag.

Gate: `tests/test_style.py::test_every_top_level_import_is_lazy`.

---

## 7. Pais, filhos e compartilhamento

- Pacote é processo vertical completo e pode aninhar quanto for útil. Evitar pacote-deus para "manter a sequência junta".
- O pai passa **inputs explícitos** e integra **outputs** dos filhos. Não entrega seu Container inteiro a cada filho. Referências read-only e acesso delimitado a um draft são permitidos.
- Descer ao filho para ver detalhes é desejado; caçar a continuação do pai em callbacks e dispatchers dispersos, não.
- **Helpers são locais por padrão** (§2: a profundidade diz quem compartilha). Um consumidor: fica local, na profundidade máxima. Dois irmãos realmente precisando: subir para o pai comum, ao lado deles, não para a raiz. Dois usos são condição necessária para compartilhar, **não obrigação**. Duplicação simples pode ler melhor — exceto política autoritativa (abaixo).
- Usos imaginados não justificam abstração. Mas política autoritativa única (privacidade, validação, commit, retry) não é duplicada.
- Pacotes novos podem ser movidos, divididos ou substituídos — atualizando produtores, consumidores, imports e testes **juntos**. Código novo não é legado: sem wrappers de compatibilidade, parsers duplos ou aliases.

---

## 8. Literais, parâmetros e configuração

- Escolha fixa local é literal no ponto de chamada: `.prepare_request(output_tokens=384, response_mode="structured")`. Não promover mecanicamente a constante de módulo, Settings ou env.
- Um parâmetro pode existir mesmo quando o valor "poderia ser buscado dentro": torna a origem visível e a transformação reproduzível em teste.

  ```python
  pipe.prepare_prompt(language="pt-BR")  # decisão fixa local
  pipe.prepare_prompt(language=parent.container.language)  # vem do pai
  ```

- Valores reais de usuário/sessão/ambiente/credencial **não** são literais. A composição inicial que os possui carrega uma vez e passa explicitamente. Filhos não consultam env/config por conta própria.
- **Pacote global não é variável global.** Um dispatcher LLM compartilhado recebe client/config por argumento; não há singleton importado por todos.
- "Carregar uma vez e passar" não significa megacontainer repassado inteiro a todos.

---

## 9. Efeitos, commit e recibos

- Efeitos externos (escrita, rede, inferência paga) acontecem em métodos com nome e docstring que os declaram, com nome de domínio quando não são publicação canônica (no código do Tavern: `open_response`, `capture_response`, `publish_checkpoint`). `commit` é reservado a "publicar uma mudança canônica com recibo".
- `commit` publica uma vez, guarda um `*Receipt` no Container e propaga a falha sem retry escondido. Recibo registra o estado real: `NOT_PUBLISHED` (alvo não substituído — **não** "nenhum efeito": diretórios pais podem ter sido criados), `PUBLISHED_NOT_DURABLE` (bytes visíveis, durabilidade a crash não confirmada; nunca tratar como rollback), `DURABLE`.
- Escrita durável: arquivo temporário no mesmo diretório → flush → fsync → replace atômico (o template traz `storage/write/`, chamado por `storing.run(WriteDocument(...))`).
- **Nunca fazer offload de uma escrita para thread (`asyncio.to_thread`) sob um lock async**: cancelar a coroutine libera o lock, mas não para o efeito no filesystem.
- Mutar drafts isolados; avançar a revisão canônica uma vez.
- **Distinguir falha pré-commit de pós-commit.** Falha na própria publicação propaga o erro de escrita com seu recibo (`AtomicWriteError.receipt`); falha **depois** da publicação (montar o resultado, observador, apresentação) vira `*ResultError` carregando o recibo. Em ambos os casos, nunca regenerar trabalho persistido. Descartar draft não desfaz efeito externo.
- Recursos (config, client, store, locks) têm **um dono explícito** com lifetime declarado. Sem caches paralelos virando autoridade.
- Toda operação sobre um recurso compartilhado (inclusive leituras) usa o lock do dono. A reentrância é **decisão explícita por recurso**: no Tavern, locks async de sessão/nome são não reentrantes (o pai adquire, o filho declara "requer lock já possuído"; um filho que readquire o mesmo lock é bug), enquanto o lock de configuração é um `RLock` reentrante por decisão, compartilhado por load/update/save.
- Vários locks: ordem fixa de aquisição documentada (Tavern: sessões em ordem lexical de ID, depois locks nomeados por `(namespace, nome)`), liberação na ordem inversa.
- **Nunca evictar locks** do registro ao apagar um registro: um waiter ou referência retida poderia sobrepor um lock novo. O registro cresce com os nomes válidos; limite os nomes na validação, não removendo locks.

---

## 10. Duas aplicações e direção de dependência

| `backend_logic` | `backend_frontend` |
| --- | --- |
| Domínio, agentes, pipelines, validação, transações, persistência, abstrações de provider/plugin. | Rotas HTTP, encoding de request/response, status/erros/SSE, assets, segurança de transporte. |
| **Nunca** importa FastAPI, Starlette, pydantic, DTOs de transporte ou `backend_frontend`. | Entra **só** por `backend_logic/run.py` (`from backend_logic import run as backend`) e importa do lógico só módulos `contracts` (os tipos dos pedidos e produtos). Nunca importa o `run` de uma família, `pipeline`, `container` ou `helpers`. Recursos (store, locks, relógio) são preparados no `lifespan` por `backend.run(PrepareResources(...))` e guardados num slot local do frontend (`ResourceSlot`); `tests/test_architecture.py` garante a porta única. |

O Tavern diz explicitamente: **"não impor cegamente detalhes do estilo ao framework frontend"**. As regras duras do frontend são direção de dependência e não duplicar negócio; nomes como `create_app`/`build_router` são idioma do framework HTTP, não violação do vocabulário de pipelines.

Decodificação do corpo HTTP também é fronteira de ingestão. **Escolha deste template** (não regra herdada do Tavern): ler bytes, passar pela mesma família JSON estrita do lógico pela porta única (`backend.run(DecodeText(...))`: duplicatas, NaN, surrogates, profundidade) e checar a forma de wire numa dataclass, respondendo com `JSONResponse`. O template evita pydantic porque seus modelos introduzem `Any` e o `disallow_any_explicit` global falharia. Se o dono preferir pydantic na borda, registre a decisão e o ajuste de gate em `architecture-log.md`; no `backend_logic`, nunca.

Handlers HTTP não resolvem defaults de domínio, não mutam estado, não aplicam regras de visibilidade e não duplicam regra de negócio: isso é um caso de uso lógico com `run` próprio.

`tests/test_architecture.py` do template garante por AST: direção das dependências, `run.py` com `run` real e import de pacotes sem rede/abertura de dados.

---

## 11. Agentes LLM

Padrões que o Tavern consolidou para qualquer projeto com papéis de modelo:

- **Papéis são provider-neutral.** Um papel (`roles/<papel>/`) monta contexto, pede uma chamada a uma porta (`Protocol`) e admite a resposta. Diferenças de provider vivem em adapters (`llm/providers/<provider>/`).
- **Privacidade antes do contexto.** O que o modelo não pode saber não entra no prompt. Nunca "pedir ao modelo para esquecer". Declare em `AGENTS.md` o que cada papel pode saber (no Tavern: IDs internos não chegam a prompts nem à prosa do leitor — invariante daquele domínio; outro produto pode precisar de IDs no prompt).
- **Proposta ≠ fato.** A saída do modelo é um `*Candidate`/`Proposed*`; vira estado só após `admit_*` sob a autoridade do domínio, e só então `commit`.
- **Saída estruturada com contrato e validação local obrigatórios.** Recurso de schema não suportado falha em vez de sumir.
- **Uma chamada lógica possui seus retries.** Orçamento explícito, backoff no `run`, recibos/evidência antes e depois do dispatch. Erro de evidência/observador não autoriza replay da geração.
- **Evidência privada e sanitizada**, chaveada pelas identidades do seu domínio (no Tavern: `session_id`, `turn_number`, `agent`); segredos nunca em logs, URLs, argumentos de CLI ou chat. **Sanitizar não desclassifica**: o que é segredo do domínio continua segredo depois de sanitizado; fragmentos crus de streaming podem reconstruir segredos.
- **Capturar o binding completo (provider, modelo, config, client) antes de esperar um lock**, para que uma troca concorrente de configuração não altere uma operação em voo.
- **Isolamento por request no client HTTP compartilhado**: requisições diretas não herdam headers, params nem cookie jar do client; auth flows e redirects desligados; a troca fecha sua resposta, não o client do dono.
- **Orçamento único de recuperação de credencial**, separado dos retries de geração e compartilhado por todas as tentativas (no Tavern: 401 pode renovar uma vez; 403 nunca renova).
- **Orçamentos de contexto em tokens**, não truncamento arbitrário por caracteres. Se só existe heurística (`chars/4`), chame-a de estimativa, não de tokenizer.
- Se o produto tem contrato de forma para texto gerado (no Tavern: pontuação da prosa), normalize num lugar central, nos campos selecionados, nunca sobre identificadores/URLs.
- **Mocks são o padrão.** Chamada real de modelo/rede/OAuth exige autorização explícita e finita; credenciais presentes não são autorização. Testes reais ficam sob marker (`-m llm`) desligado por padrão.

---

## 12. Processo: escrever, tipar, ensaiar, só então preencher

### 12.1. Sequência

1. Levantar capacidades, entradas/saídas, autoridades e efeitos (das fontes, do produto, do dono).
2. Escrever contratos e composições **reais** no código.
3. Verificar tipagem, imports e vínculos.
4. **Ensaiar os runs com fakes tipados**, incluindo falhas pertinentes.
5. Corrigir lacunas/contradições reveladas.
6. Walkthrough com o dono, se a autorização exigir.
7. Só então delegar o preenchimento de métodos ou conjuntos coesos.

Lógica ainda não implementada fica explícita:

```python
def prepare_prompt(self, *, language: str) -> Self:
    """Read input; set prompt; no I/O and no other field changes."""
    raise NotImplementedError("summarizer.prepare_prompt")
```

Nunca retornar sucesso vazio para fingir funcionamento. `pass` em função com retorno pode esconder retorno inválido. Mocks ficam em testes, nunca como fallback de produção.

### 12.2. O ciclo e o retorno ao esqueleto

**Levantar → escrever/reajustar contratos e composições → ensaiar → implementar/delegar → integrar → confrontar de novo com as fontes.**

Depois de integrar, decidir:

- **Poucas lacunas locais** (capacidade e autoridade já representadas): corrigir direto e conferir consumidores.
- **Ausências estruturais numerosas ou acopladas** (faltam processos, ownership, transações, ligações): voltar ao desenho em código, ampliar e reajustar o que já existe, ensaiar, e só depois outra onda.

Erro de typing repetido pode denunciar tipo errado, autoridade ausente ou pacote no lugar errado. Não acumular conversões, parâmetros e métodos para tornar o gate verde. Também não redesenhar tudo por um typo.

### 12.3. Ensaio (simulação do esqueleto)

- Fakes **tipados** que respeitam a assinatura e preenchem campos coerentes com as pré/pós-condições. Nada de mocks permissivos que aceitam qualquer atributo.
- Exercitar **runs reais**, trocando apenas folhas/fronteiras não implementadas — sem reescrever a orquestração dentro do teste.
- Dados significativos cruzando pacotes; verificar campos preservados/alterados, ordem, handoffs, branches, falhas, cancelamento.
- Fake que devolve constante desconectada do input torna o teste vacuamente verde.
- Teste de concorrência sem `await` dentro da seção crítica não observa o lock: ensaie o lock com um holder que espera dentro dele (ver `tests/test_notes_save.py`). Guardas também precisam de teste: um scanner de imports que só lia `node.module` passava vazio.
- Mostrar casos que o contrato rejeita quando isso esclarece uma distinção, inclusive **verificações estáticas negativas proporcionais** (trocar IDs/estágios nominais deve falhar no mypy). Não deixar fixtures propositalmente inválidas misturadas ao código de produção.
- Semântica de cópia/snapshot precisa ser ensaiada em runtime: nome, tipo ou `Self` não congelam objetos nem garantem cópia.
- **Registrar quais ligações foram simuladas**, com que premissas e quais ainda não foram. O registro não pode se verificar apenas contra si mesmo.
- **Código e teste podem compartilhar a mesma interpretação errada.** Confrontar com fontes e consumidores reais. Corrigir a fixture errada; não afrouxar a implementação correta.

### 12.4. Testes por pacote ou trecho

- A fronteira natural é o pacote/segmento: entrada, saída, sequência e efeitos conhecidos. Selecionar por risco e dúvida, não quota por método.
- Mockar apenas o filho fora da investigação.
- **Começar no meio:** preparar um Container válido naquela etapa e executar só o trecho suspeito. Nunca um estado que a pipeline real não produziria.

```python
pipe = Pipe.get(ListNotes())
pipe.container.files = ("b.json", "a.txt")  # estado real logo após scan_directory

listed = pipe.select_stems(suffix=".json").admit_names().sort_names().materialize()
```

- Testes default usam diretório de dados temporário, providers mockados e fixtures sintéticas. Dados reais nunca são fixture.

---

## 13. Coordenador como arquiteto; trabalho delegado

O coordenador é **arquiteto**, não o desenvolvedor padrão de todas as folhas: possui levantamento global, contratos, composições, ensaio e integração. Pode corrigir um gap local pequeno; com muitas lacunas, recupera o desenho e prepara outra onda.

**Pacote de delegação** (o que cada agente implementador recebe):

- Assinatura, tipos, inputs/outputs, dependências.
- Campos do Container lidos, exigidos, escritos e preservados.
- Efeitos permitidos/proibidos, falhas, cancelamento, invariantes.
- Fixtures/ensaios e oráculos do trecho.
- **Arquivos sob seu ownership exclusivo**, sem permissão para redesenhar contratos consumidos.

O agente não reconstrói o sistema para descobrir o contrato. Se faltar informação ou o contrato for impossível, **reporta a lacuna** ao coordenador em vez de inventar. Sem edição simultânea no mesmo arquivo. Sem delegação recursiva, salvo decisão do dono.

**Antes de julgar o resultado de uma onda, classificar a ausência:**

1. Erro de implementação — contrato e ligação existiam; a folha não cumpriu.
2. Erro/omissão arquitetural — contrato insuficiente ou composição consumidora ausente.
3. Capacidade não distribuída — nunca esteve nos escopos entregues.

Redistribuir um método resolve (1); não inventa a autoridade de (2) nem conclui (3).

Número de agentes, testes passando e percentuais **não** são evidência de conclusão ou qualidade. Ganho de taxa de acerto por contrato preciso é hipótese a medir, não promessa.

---

## 14. Documentação honesta

- **README de pacote** (quando o pacote tem decisões relevantes): o que ele é, o que **não** é, inputs/responsabilidades, correções explícitas em relação à fonte, e o que falta. Ex.: "This is a projected context, **not** a complete prompt."
- **Vocabulário** (`docs/design/vocabulary.md`): nomes definidos pelo dono e propostas em observação, com limite de cada uma.
- **Registro de arquitetura** (`docs/design/architecture-log.md`; no Tavern o equivalente é `docs/design/architecture-experiment.md`), por decisão: observação e fonte → estado (ausente/ensaiado/implementado/integrado/verificado) → diagnóstico (1/2/3 acima) → decisão e razão → evidência necessária e o que ela **não** provará → resultado posterior.
- O registro aponta para o código; não vira árvore paralela que pareça pronta. Documentos históricos não são reescritos para fingir cobertura passada.
- Ao reportar: "X ensaios com folhas finitas e N casos reais demonstram estes handoffs, **não** Y". Nunca "funciona" sem evidência do componente real.

---

## 15. Dados, segredos e experimentos

- Dados reais e cópias são privados, ignorados pelo git e nunca fixtures.
- Nunca imprimir configs/tokens nem colocá-los em arquivos versionados, storage do browser, URLs, argumentos ou chat.
- Mudança de representação persistida exige versão de schema e decisão explícita: migração autorizada ou rejeição clara. Sem parsers duplos nem defaults legados.
- Rascunhos/scratch em `.dumps/` (ignorado).
- Rede, modelo pago, OAuth, commit, push e publicação exigem autorização explícita.

---

## 16. Anti-padrões

| Sintoma | Por que é errado | Fazer |
| --- | --- | --- |
| `self.result`, `self.ctx`, `have()`, `build()` | Divide o vocabulário | `self.container`, `get`, `materialize` |
| `def x(self) -> Self: pass` | Finge sucesso | `raise NotImplementedError("pacote.metodo")` |
| `assert self.container.x` | Some com `-O` | `if ... is None: raise RuntimeError(...)` |
| `MAX_TOKENS = 384` no topo, usado uma vez | Falsa configuração | literal no ponto de chamada |
| `from app.settings import SETTINGS` dentro de um filho | Estado global | passar explicitamente do dono |
| `dict[str, Any]` atravessando o domínio | Esconde o contrato | campos declarados; JSON só na ingestão |
| Engine de steps/registry de fases | Esconde a ordem | ordem fixa no `run` |
| Pai entrega seu Container inteiro ao filho | Acoplamento difuso | inputs explícitos |
| `helpers/` com função de um consumidor | Abstração prematura | manter local |
| Wrapper de compatibilidade para código novo | Mantém duas verdades | migrar consumidores juntos |
| Handler HTTP aplicando regra de negócio | Lógica fora do dono | novo `run` lógico |
| Mock que aceita qualquer atributo | Teste vacuamente verde | fake tipado coerente |
| Retry depois do commit porque o log falhou | Duplica efeito | `*ResultError` com recibo |
| `asyncio.to_thread(storing.run, WriteDocument(...))` sob lock | Cancelamento libera o lock com a escrita ainda rodando | escrita síncrona dentro do lock |
| Módulo solto (`files.py`, `jsonvalue.py`, `utils.py`) | Leitor não sabe onde começar nem o que é | pacote por operação com os cinco arquivos |
| Frontend chamando `notes.run` ou `storage` direto | Porta lateral; a subida some | `backend_logic/run.py` + `contracts` |
| `validate_*` que faz `.strip()` | Corrige em vez de verificar | rejeitar, ou etapa de normalização nomeada |
| "Testes verdes, está pronto" | Confunde mecânica com produto | relatar o que foi e não foi provado |

---

## 17. Checklist

- [ ] O projeto é navegável por arquivos, tipos e chamadas reais antes da lógica?
- [ ] Toda pasta tem os cinco arquivos e nenhum outro? Todo caso de uso desce de `backend_logic/run.py` por `match` até a folha?
- [ ] Cada `run` mostra sua história sem achatar a dos filhos?
- [ ] Vocabulário consistente; nomes novos registrados como proposta?
- [ ] Container com vazios declarados no constructor (`None` ou vazio tipado), campos precisos, intermediários só nele?
- [ ] Nenhum conhecimento de domínio escondido em `Any`, coleções vagas ou casts?
- [ ] Tipos distinguem alternativas reais; pré-condições cobrem o que tipos não provam?
- [ ] Literais/parâmetros mostram decisões e origens, sem globals nem megacontainer?
- [ ] Compartilhamento tem consumidores reais e melhora a leitura? Cada pacote mora no menor ancestral comum dos seus consumidores?
- [ ] Paralelo é um `TaskGroup` de `run`s irmãos, integrado em ordem fixa depois da barreira?
- [ ] Indentação, awaits, efeitos e barreiras contam a mesma história?
- [ ] Runs ensaiados com fakes tipados e dados coerentes entre pacotes?
- [ ] Consigo isolar um trecho preparando um Container intermediário válido?
- [ ] Um agente entende seu método sem inventar arquitetura?
- [ ] Lacuna é local ou exige reajustar o esqueleto?
- [ ] Produtores e consumidores reorganizados juntos, sem wrapper?
- [ ] Falha pré-commit e pós-commit distinguidas, com recibo?
- [ ] Não confundi tipagem/simulação com produto pronto, nem hipótese com ganho medido?

---

## 18. O que é específico do Alex Tavern (não copiar como regra geral)

Estas regras existem no Tavern por causa do seu domínio ou da sua situação. Num projeto novo, entram somente se o dono decidir, reescritas para o domínio dele:

- **Invariantes de roleplay:** nenhum modelo sabe que um humano controla um personagem; pensamentos privados ao autor e ao Director; Director possui resultados físicos, Character possui falas; Historian resume só evidência pública. **Transferível:** a forma — cada projeto lista seus invariantes de domínio, de privacidade e de autoridade entre papéis no `AGENTS.md`.
- **Perfil reconstrução:** snapshot do app antigo em `.dumps/reference-source` como referência privada (nunca importável), paridade por simulações diferenciais, preservar inventário de rotas. Use só se o projeto novo reconstrói um existente.
- **Enxames de ≥50 agentes:** autorização específica da task136 do Tavern, não quota.
- **Críticos automáticos desligados:** decisão do dono do Tavern. Em outro projeto, a política de revisão por críticos é do dono daquele projeto.
- **Provider/modelo preferido** (Grok/SuperGrok), Python 3.14 (o template usa 3.15 pelo `lazy import`, §6.1), nomes `backend_logic`/`backend_frontend`: preferências locais; mantenha se fizerem sentido, mas registre como decisão.
- **Identidades e formas do domínio:** `session_id`/`turn_number`, "prosa do leitor", contrato de pontuação, IDs fora do prompt. **Transferível:** a forma — chaveie evidência e declare o que cada papel sabe com as identidades do seu domínio.

E o que é **escolha deste template**, não herança do Tavern: os cinco arquivos obrigatórios sem módulos soltos, a subida por famílias com `match` desde `backend_logic/run.py`, mecanismos como um pacote por operação (`storage/*`, `json/*`), alias de filho via módulo (`encoding.run`), a fraseologia `Require …; set …` nas docstrings, a família JSON estrita no corpo HTTP sem pydantic, e o domínio-exemplo `notes`/`roles/summarizer`.

Origem do estilo: DTP (`al4xdev/dtp`, `compiler/endpoint.py` e `transcribe_mp4/endpoint.py`), consolidado no Tavern nas revisões r3–r6. `endpoint`/`have`/`arun` são nomes históricos, não convenções.

**Resumo: escrever, tipar e ensaiar o projeto em Python; revisar suas fronteiras; só depois preencher as transformações. Voltar ao esqueleto quando as lacunas forem estruturais. O código é o blueprint, não uma promessa de blueprint futuro.**