# Instruções para agentes

Este projeto nasce no estilo de pipelines verticais legíveis. Antes de mexer num pacote, leia [docs/design/vertical-pipelines.md](docs/design/vertical-pipelines.md) e [docs/design/vocabulary.md](docs/design/vocabulary.md). Este arquivo é um resumo imperativo, não uma arquitetura concorrente; em conflito, o guia vale. Decisões do dono deste projeto (seções marcadas abaixo) valem sobre o guia.

## Projeto

<!-- PREENCHER: o que o produto faz, para quem, e o que ele NÃO é. -->

## Regras de código

- O código é o blueprint: contratos, Containers, assinaturas e `run` reais antes da lógica. Lógica ausente é `raise NotImplementedError("pacote.metodo")`, nunca sucesso vazio.
- Vocabulário fixo: `run.py`/`run`, `Pipe`, `Pipe.get(initial)`, `Container`, `self.container`, métodos fluentes `-> Self`, terminal `materialize`. Proibido `have`/`start`/`create`, `result`/`build`/`finish`, `self.context`/`self.state`.
- **Decisão do dono:** toda pasta de `backend_logic` tem exatamente `__init__.py` (só docstring, sem I/O), `contracts.py`, `container.py`, `pipeline.py`, `run.py`, e nenhum outro módulo. Comece a ler sempre pelo `run.py`/`def run`. `contracts.py` guarda o pedido, o produto, os tipos dos campos do Container e das mutações, portas e erros.
- **Subida:** a leitura começa em `backend_logic/run.py`. Família declara `type <Família>Request = A | B` e despacha com `match` visível (`@overload` por caso, `assert_never` no fim); todo ancestral de família é família. Processo tem cadeia; seus filhos são etapas. Novo caso de uso = pedido nomeado no pacote que o atende + união na família + `case` em cada `run.py` acima.
- Mecanismo compartilhado é um pacote por operação com nome legível (`storage/write/`, `json/decode/`), nunca módulo solto (`files.py`, `jsonvalue.py`).
- Cada pasta é um pacote e a profundidade diz quem o usa: um consumidor → dentro dele; irmãos → no pai comum, ao lado deles; nunca na raiz "por precaução". Autoridade compartilhada (ex.: `notes/name/`) é um pacote irmão, não helper.
- Paralelo = `asyncio.TaskGroup` chamando `run`s de pacotes irmãos; o pai integra os resultados em ordem fixa depois da barreira.
- Filho é chamado pelo seu `run` com alias que nomeia a ação/produto (convenção do template: `lazy from .encode import run as encoding` → `encoding.run(...)`). Pai importa só `run`/`contracts` do filho.
- Pedidos e produtos nomeados (`SaveNote` → `SavedNote`), não `Input`/`Output` genéricos. Container: vazios declarados (`None` ou vazio tipado); produto que pode ser `None` vai embrulhado (`Validated`).
- Ordem, branches, locks e awaits ficam visíveis no `run`, com indentação crescente como sequência. O `ruff format` já ignora `backend_logic/**/run.py` (config no `pyproject.toml`): não escreva `# fmt: off`/`# fmt: on`, e formate o `run.py` à mão.
- Todo método de `Pipe` (inclusive `get` e `materialize`) tem docstring declarando o que lê, exige, escreve e preserva, efeitos e falhas (fraseologia do template: `Require …; set …`).
- Campo obrigatório ausente: `if x is None: raise RuntimeError(...)`, nunca `assert`.
- Literal local fica no ponto de chamada. Config, credenciais e recursos são carregados pelo dono e passados explicitamente; nada de global.
- Tipagem estrita: sem `Any`, coleções sem parâmetro, `cast`/`type: ignore` para esconder contrato. JSON amplo só na fronteira de ingestão. Códigos de erro e fases são `Literal`, nunca `str`.
- **Decisão do dono:** Python 3.15, e todo import de topo em `backend_logic`/`backend_frontend` é `lazy` (`lazy import x`, `lazy from .contracts import Y`). Exceções: `from __future__` e imports dentro de função. Se um pacote não suportar lazy, troque aquele import por `import` normal e registre o módulo em `EAGER_IMPORTS` (`tests/test_style.py`) com o motivo, mais uma entrada no `architecture-log.md` (guia §6.1). Erro de import agora aparece no primeiro uso: teste cada `run`.
- Função auxiliar é local ao `pipeline.py` por padrão; compartilhar só com consumidores reais, como pacote no menor ancestral comum. Código novo não ganha wrapper de compatibilidade.
- Verbos herdados: `validate_*` (verifica, nunca corrige), `prepare_*`, `project_*`, `admit_*`, `commit`. Demais nomes de método são locais e de domínio.
- `commit` publica uma mudança canônica uma vez e guarda `*Receipt`. Falha da publicação propaga com seu recibo; falha depois dela vira `*ResultError` com o recibo. Sem retry escondido.
- Nunca faça offload de escrita para thread sob lock async. Reentrância de lock é decisão por recurso; múltiplos locks em ordem fixa; nunca evicte locks.
- `backend_logic` nunca importa FastAPI/Starlette/pydantic/`backend_frontend`. `backend_frontend` entra só por `backend_logic/run.py` e importa só módulos `contracts`; recursos nascem no `lifespan`.
- Papéis LLM são provider-neutral, aplicam privacidade antes do contexto, tratam saída como proposta e a admitem localmente. Orçamentos em tokens.

## Processo

1. Levantar → contratos e composições em código → ensaiar com fakes tipados → implementar/delegar → integrar → confrontar com as fontes.
2. Lacuna local: corrija. Ausência estrutural: volte ao esqueleto antes de outra onda.
3. Ao delegar, entregue assinatura, campos do Container lidos/escritos, efeitos, falhas, fixtures e arquivos exclusivos. Implementador que encontra contrato impossível reporta, não inventa.
4. Classifique falhas: implementação / omissão arquitetural / capacidade não distribuída.
5. Novo nome recorrente → proposta em `vocabulary.md`. Decisão estrutural → `architecture-log.md`.

## Gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

Nunca relaxe um gate para obter verde. Gates verdes não provam produto pronto: relate o que foi ausente, ensaiado, implementado, integrado e verificado.

A configuração de ruff (lint e format), mypy e pytest vive no `pyproject.toml` e **faz parte do template**: um projeto novo nasce com ela pronta. Não crie `ruff.toml`, `mypy.ini` ou `setup.cfg` paralelos, não passe flags que a contornem e não a altere sem decisão do dono registrada em `docs/design/architecture-log.md`.

## Dados, segredos e autorizações

- `.data/` (dados de runtime) e `.dumps/` (scratch, referências) são privados e ignorados pelo git. Dados reais nunca são fixtures.
- Nunca imprima nem versione tokens/configs privadas.
- Rede, modelo pago, OAuth, commit, push e publicação exigem autorização explícita.

<!-- PREENCHER: autorizações concretas vigentes (ex.: "chamadas reais ao modelo X permitidas sob -m llm até <data>"). -->

## Invariantes do domínio

<!-- PREENCHER: invariantes de privacidade, autoridade entre papéis e o que cada papel pode saber.
Ex. (Tavern): "nenhum modelo sabe que um humano controla um personagem; Director possui resultados físicos". -->

## Política de provider e modelo

<!-- PREENCHER: providers permitidos, modelo padrão por papel, onde vivem adapters (llm/providers/<provider>/). -->

## Política de críticos e delegação

<!-- PREENCHER: se revisões por subagentes críticos estão ligadas, número máximo de agentes por onda, delegação recursiva permitida ou não. -->