# Registro de arquitetura

Uma entrada por decisão estrutural. O registro aponta para o código; não é uma árvore paralela que pareça pronta. Entradas antigas não são reescritas para fingir cobertura passada — acrescente uma entrada nova com o resultado.

Estados: **ausente** · **ensaiado** (run real com fakes tipados) · **implementado** · **integrado** (consumidores reais ligados) · **verificado** (evidência do componente real).

Diagnóstico de ausência: **(1)** erro de implementação · **(2)** omissão arquitetural · **(3)** capacidade não distribuída.

## Modelo de entrada

```markdown
### AAAA-MM-DD — título curto

- Observação e fonte: o que foi visto, onde (arquivo:linha, fonte, teste).
- Estado: ausente / ensaiado / implementado / integrado / verificado.
- Diagnóstico: (1) / (2) / (3) e por quê.
- Decisão e razão: o que muda no código; alternativas descartadas.
- Evidência necessária: o que provará, e o que ela NÃO provará.
- Resultado posterior: preenchido depois, com evidência.
```

## Entradas

### Template inicial — borda HTTP sem pydantic

- Observação e fonte: modelos `pydantic.BaseModel` falham `disallow_any_explicit` no mypy estrito.
- Estado: implementado e testado em `backend_frontend/notes/routes.py`, `tests/test_http_notes.py`.
- Diagnóstico: escolha de fronteira, não lacuna.
- Decisão e razão: decodificar o corpo com `json` stdlib (`object` → checagens → dataclass de wire). Mantém o gate inteiro sem exceção.
- Evidência necessária: testes de corpo malformado retornam 422 antes do run lógico. Não prova segurança de transporte, autenticação nem limites de tamanho de corpo.
- Resultado posterior: substituído pela entrada "Codec estrito compartilhado" abaixo.

### Template inicial — codec estrito compartilhado pelas três fronteiras de ingestão

- Observação e fonte: revisão crítica reproduziu `{"body": "\ud800"}` passando pelo `json.loads` da borda HTTP e virando 500 (`AtomicWriteError` em `serialize`); `"[" * 2000` escapava do summarizer como `RecursionError`; a borda HTTP aceitava chaves duplicadas.
- Estado: implementado e testado (`tests/test_storage_codec.py`, `tests/test_http_notes.py`, `tests/test_summarizer.py`).
- Diagnóstico: (1) erro de implementação — a política de JSON estava duplicada e incompleta.
- Decisão e razão: `backend_logic/codec/jsonvalue.decode_text` é a única política (duplicatas, NaN/Infinity, surrogates isolados, profundidade) e toda rejeição é `ValueError`; a borda HTTP o usa e só checa a forma de wire. O teste de arquitetura libera `codec` para o frontend, mantendo `storage`/`pipeline`/`container`/`helpers`/`_privados` proibidos, e agora inspeciona os nomes em `from X import a`.
- Evidência necessária: corpos e respostas hostis rejeitados como 422 / `SummaryRejectedError`. Não prova limite de tamanho de corpo nem custo de parsing.
- Resultado posterior: —

### Template inicial — validação sem correção, confinamento por segmento, recursos preparados

- Observação e fonte: `validate_name` fazia `.strip()` e aceitava `"²½"` via `str.isalnum()`; `FileStore.path`/`resolve_directory` aceitavam `""`, `"."`, `"notes/."`, `\`, NUL; documento `notes/a.json` com `name: "b"` era aceito como predecessor; `runtime/application` usava `create_locks` e construía `UtcClock()` dentro de `materialize`; o recibo perdia `size_bytes` quando o fsync do diretório falhava depois do replace.
- Estado: implementado e testado (`tests/test_notes_save.py`, `tests/test_storage_codec.py`).
- Diagnóstico: (1) erros de implementação contra regras já escritas no guia.
- Decisão e razão: rejeitar em vez de normalizar (conjunto ASCII explícito; segmentos crus); conferir nome do documento contra o caminho; `prepare_store`/`prepare_locks`/`prepare_clock` com `Container.clock`; recibo mantém o tamanho publicado. Falha da publicação continua propagando `AtomicWriteError` com recibo `PUBLISHED_NOT_DURABLE` — não é `NoteResultError`, porque a falha é da própria publicação, não posterior a ela.
- Evidência necessária: testes de rejeição e de fsync falho. O teste de lock agora segura um `await` dentro do lock; o de `gather` só prova a sequência "segunda criação conflita", não exclusão. Não prova comportamento com symlinks nem multiprocesso.
- Resultado posterior: a regra de nome saiu de `save.validate_name` para `notes/name/` (entrada abaixo).

### Template inicial — padrão à risca: autoridade de nome por profundidade, codec oficial, gate de estilo

- Observação e fonte: a regra de nome vivia só em `save.validate_name`; `save/decode` admitia qualquer `name` (inclusive `"../escaped"`) e `list` devolvia stems crus como `str`. No Tavern, `catalog/presets/name/` é a autoridade única usada por `read`/`save`/`delete`/`avatar`/`list/entry`. Faltavam docstrings em `get`/`materialize`, e nenhum gate verificava o vocabulário. O dono pediu o padrão à risca mesmo onde o código do Tavern, inacabado, não o segue.
- Estado: implementado e testado (`tests/test_notes_name.py`, `tests/test_notes_list.py`, `tests/test_notes_save.py`, `tests/test_style.py`).
- Diagnóstico: (2) omissão arquitetural — política autoritativa duplicável e um lugar na árvore que não dizia quem a usa.
- Decisão e razão: `notes/name/` no nível dos irmãos que a usam; `save.validate_name`, `save/decode.admit_record` e `list.admit_names` a chamam. Nome rejeitado vindo do disco é corrupção (`ValueError` → 500), não `invalid_name` (422). `list` separa `stems` de `names: tuple[NoteName, ...]`. `codec/` vira convenção do template (irmão de `storage` na raiz; única importação extra do frontend). `tests/test_style.py` verifica anatomia, `Pipe`/`get`/`materialize`, aliases proibidos, `-> Self`, docstrings, `self.container` como único estado, imports só de `run`/`contracts` de outros pacotes e ausência de `assert`, e tem teste do próprio scanner.
- Evidência necessária: as regras falham contra fontes sintéticas que as violam e passam contra o template. Não prova que as docstrings dizem a verdade nem que um `validate_*` não corrige valores — isso continua sendo revisão.
- Resultado posterior: `codec/` e os módulos soltos de `storage` foram substituídos por pacotes (entrada abaixo).

### 2026-11-04 — cinco arquivos obrigatórios, subida por famílias, mecanismos como pacotes

- Observação e fonte: o dono, lendo o template, não sabia por onde começar: `backend_logic/` não tinha `run.py`; `codec/jsonvalue.py`, `storage/files.py` e `storage/locks.py` eram módulos soltos com nomes que não dizem o que fazem; `notes/` tinha um `contracts.py` sem `run`. Decisão do dono: os nomes de arquivo são obrigatórios; toda leitura começa num `run.py`/`def run`; `contracts.py` guarda os tipos dos campos do Container e das mutações.
- Estado: implementado e testado (`tests/test_style.py`, `tests/test_architecture.py`, `tests/test_backend_run.py`, `tests/test_storage_json.py` e a suíte reescrita).
- Diagnóstico: (2) omissão arquitetural — a árvore não mostrava onde o código roda.
- Decisão e razão: toda pasta de `backend_logic` tem exatamente `__init__`/`contracts`/`container`/`pipeline`/`run`. Família = `type <X>Request = A | B` + `match` no `run` com `@overload`; a raiz é família e o frontend só entra por ela. Mecanismos viram `json/{validate,decode,encode}` e `storage/{path,read,write,scan,lock}`. `Input`/`Output` viram pedidos nomeados (`SaveNote`, `SummarizeNote`, `PrepareResources`). Recursos nascem no `lifespan` (nada toca disco ao construir o app). Mudança intencional: listar notas não cria mais `notes/` (diretório ausente → `()`). mypy: `disallow_any_expr` vale para todo `backend_logic`, com exceção só em `json.decode` (contém o `Any` de `json.loads`). Alternativa descartada: manter módulos soltos para mecanismos (leniência do Tavern), rejeitada pelo dono por legibilidade.
- Evidência necessária: gate de estilo falha para pasta sem os cinco arquivos, módulo com outro nome, família sem `match` ou família sob processo; teste da raiz alcança cada família e preserva JSON `null`. Crítico independente reproduziu falsy JSON (`null`, `0`, `[]`, `""`, `{}`), listagem de store novo e rejeições JSON estritas sem achar regressão. Não prova que cada `match` é exaustivo além do que o `assert_never` + mypy garantem, nem cobre imports frios por módulo.
- Resultado posterior: —

### 2026-11-04 — `run.py` fora do formatter, configuração de ferramentas como parte do template

- Observação e fonte: cada `run.py` repetia `# fmt: off`/`# fmt: on` em volta da cadeia para o ruff não achatar a indentação semântica; era ruído em todo arquivo e fácil de esquecer num pacote novo. O dono pediu que linters e formatadores venham configurados no template.
- Estado: implementado e testado (`tests/test_style.py::test_run_composition_is_left_to_the_author_not_the_formatter`).
- Diagnóstico: escolha de ferramenta, não lacuna de domínio.
- Decisão e razão: `[tool.ruff.format] exclude = ["backend_logic/**/run.py"]` e `[tool.ruff] force-exclude = true` (sem ele, `ruff format caminho/run.py` vindo de editor ou agente ignoraria o exclude). Todos os `# fmt:` foram removidos e o gate os proíbe em `backend_logic`. O linter continua aplicado ao `run.py`. `docs/**/*.md` também sai do formatter: o ruff formata blocos Python dentro de Markdown, e os trechos do guia citam composições de `run.py`. Alternativa descartada: manter `# fmt: off` por arquivo (ruído repetido; omissão silenciosa num pacote novo).
- Evidência necessária: `ruff format --check .` passa de 124 para 100 arquivos (21 `run.py` e 3 `.md` de `docs/` fora); `ruff format --check backend_logic/notes/save/run.py` não toca o arquivo. Não prova que o `run.py` escrito à mão está bem indentado: isso é revisão.
- Resultado posterior: —

### 2026-11-04 — exemplo real de `TaskGroup` (`roles/digest/`) e `await` em linha própria

- Observação e fonte: o §4.4 só tinha um trecho ilustrativo de `TaskGroup`; nenhum código do template rodava em paralelo. O dono perguntou se a cadeia pode continuar depois do `await`.
- Estado: implementado e testado (`tests/test_roles_digest.py`, `tests/test_backend_run.py`).
- Diagnóstico: (2) omissão arquitetural — o cookbook prescrevia um padrão sem demonstrá-lo.
- Decisão e razão: `roles/digest/` é processo irmão de `roles/summarizer/` e roda um `summarizing.run` por nota num `asyncio.TaskGroup` visível no `run`. O orçamento (`max_notes=8`) e nomes distintos são validados antes de qualquer chamada paga. A integração acontece depois da barreira, em ordem de pedido. Política de falha: `TaskGroup` (a primeira rejeição cancela o resto, `ExceptionGroup`, nunca digest parcial). `RolesRequest` vira `SummarizeNote | DigestNotes`; a raiz ganha o `case` e o produto `RolesResponse`. Async: mantido o `await pipe.x()` em linha própria. Encadear após o `await` é válido, mas aninha parênteses a partir da segunda etapa async e esconde o ponto de suspensão. Alternativa descartada: `gather(return_exceptions=True)`, que devolveria digest parcial sem contrato para isso.
- Evidência necessária: o teste de concorrência trava se as chamadas forem sequenciais (o fake da primeira nota espera a segunda terminar, sob `asyncio.timeout(1)`); o digest sai em ordem de pedido mesmo com conclusão invertida; uma rejeição cancela a chamada pendente; pedido vazio, acima do orçamento ou duplicado não chama o modelo. Não prova limite de concorrência contra o provider real (não há semáforo) nem custo agregado em tokens.
- Resultado posterior: verificado por mutação numa cópia descartável. O laço sequencial fez falhar os testes de concorrência e de rejeição por timeout; `gather(return_exceptions=True)` com digest parcial fez falhar o de rejeição; sem `validate_notes`, falharam os 3 casos inválidos. O teste de rejeição ganhou `asyncio.timeout(1)`, porque sem ele a mutação `gather` travaria em vez de falhar.

### 2026-11-04 — contratos mais estritos: códigos fechados e revisão nominal

- Observação e fonte: o §6 manda "escolhas finitas conhecidas são `Literal`/`Enum`, não `str`", mas `NoteConflictError.code`, `NoteValidationError.code` e `AtomicWriteError.phase` eram `str`; `language` era `str`; `revision`/`expected_revision` eram `int` crus; `NoteView.title` era `str`, embora venha de um `NoteName`. O dono explicou o motivo do cookbook: o modelo de fronteira tipa os contratos e modelos mais baratos preenchem os métodos, então tudo o que o tipo não fecha é espaço para furar o contrato sem que o gate veja (rascunho em `../ideias/contratos-para-delegacao.md`, ainda não destilado).
- Estado: implementado e testado.
- Diagnóstico: (1) erro de implementação contra regra já escrita no §6.
- Decisão e razão: `type NoteConflictCode = Literal["note_exists", "note_missing", "revision_conflict"]`, `type NoteValidationCode = Literal["invalid_name"]`, `type WritePhase = Literal[...]` (seis fases em ordem), `type Language = Literal["en", "pt-BR"]`, `Revision = NewType("Revision", int)` em `notes/save/contracts.py` e `NoteView.title: NoteName`. O frontend embrulha o `expected_revision` do cliente em `Revision` (nomeia a alegação; o save a compara). Fica de fora por ora: `NoteDocument` como `TypedDict` (não é atribuível a `JsonValue` sem conversão), orçamentos (`output_tokens`, `max_*`) como `NewType` (pioraria a leitura do `run` com `TokenBudget(256)`), `SelectLock.kind` (mecanismo não deve depender de domínio).
- Evidência necessária: mypy passou a rejeitar 7 pontos nos testes onde um `int` cru virava revisão, corrigidos com `Revision(n)`. Um código de erro digitado errado agora é erro de tipo (sonda com mypy). Gate mecânico: `tests/test_style.py::test_error_codes_and_phases_are_closed_sets` proíbe parâmetro ou atributo `code`/`phase` anotado como `str` em `backend_logic`; o scanner tem autoteste. O gate só olha esses dois nomes, não descobre sozinho outros conjuntos fechados. Não prova que os valores dos `Literal` batem com o mapeamento HTTP; isso segue coberto por `tests/test_http_notes.py`.
- Resultado posterior: —

### 2026-11-04 — Python 3.15 e todo import de topo `lazy` (PEP 810)

- Observação e fonte: o dono pediu Python 3.15 só para ter `lazy import`, com fallback documentado para import normal quando um pacote não suportar.
- Estado: implementado e testado.
- Diagnóstico: escolha de plataforma, não lacuna de domínio.
- Decisão e razão:
  - `requires-python = ">=3.15"`, ruff `target-version = "py315"`, mypy `python_version = "3.15"`.
  - Todo import de topo em `backend_logic` e `backend_frontend` virou `lazy`. A conversão foi feita por AST, para não tocar docstrings.
  - Gate `tests/test_style.py::test_every_top_level_import_is_lazy`, com exceções em `EAGER_IMPORTS` (vazio hoje; cada entrada leva o motivo e um registro aqui). `tests/` fica eager.
  - Alternativa descartada: ficar no 3.14 com imports normais.
- Evidência necessária:
  - `uv lock` em CPython 3.15.2 resolveu 37 pacotes.
  - Há wheel cp315 manylinux x86_64 para pydantic-core, uvloop, httptools, websockets, mypy e librt; watchfiles usa abi3. `pyyaml` 6.0.3 (vem do `uvicorn[standard]`) não tem wheel cp315: foi compilado do sdist sem a extensão C (`yaml.__with_libyaml__ = False`), o que funciona, só que mais lento.
  - Ruff, format, mypy e pytest verdes (114 testes).
  - O lazy é real: depois de importar `backend_logic.run`, `backend_logic.storage.write.pipeline` e `backend_logic.roles.digest.run` não estão em `sys.modules`.
  - Fallback verificado numa cópia em `/tmp` com todos os `lazy` removidos: 101 testes fora do `test_style` verdes e mypy limpo, e o gate falha apontando cada import eager.
  - Nesta build, `-X lazy_imports` aceita só `all`/`normal`, sem opção para desligar: o fallback é editar o código.
  - Não prova que cada caminho de import resolve; isso depende dos testes exercitarem cada `run`, porque erro de import agora aparece no primeiro uso.
- Resultado posterior: —