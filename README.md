# cookiebook

Guia de referência e template para novos projetos de agentes nascerem no estilo do **Alex Tavern 2**: mesma estrutura, mesma nomenclatura de domínio (`run`, `Pipe`, `Container`, `contracts`, `materialize`, verbos e sufixos) e a mesma filosofia — o código é o blueprint, tipado e ensaiado antes da lógica.

## O que tem aqui

| Caminho | Para quê |
| --- | --- |
| [`template/docs/design/vertical-pipelines.md`](template/docs/design/vertical-pipelines.md) | **O guia.** Princípios, anatomia de pacote, vocabulário, composição no `run`, Container, tipagem, efeitos/recibos, duas aplicações, agentes LLM, processo de ensaio, coordenador/delegação, anti-padrões, checklist e o que é específico do Tavern. |
| [`template/AGENTS.md`](template/AGENTS.md) | Resumo imperativo para agentes, com lacunas `<!-- PREENCHER -->` para as decisões do dono do projeto novo. |
| [`template/docs/design/vocabulary.md`](template/docs/design/vocabulary.md) | Nomes definidos e propostas em observação. |
| [`template/docs/design/architecture-log.md`](template/docs/design/architecture-log.md) | Modelo de registro de decisões. |
| [`template/`](template/) | Projeto Python 3.15 mínimo (imports `lazy`) que roda e passa nos gates: exemplos reais de cada padrão. |
| [`ideias/`](ideias/) | Rascunhos do dono ainda não destilados no cookbook (ex.: contratos para delegação entre modelos). |

`.dumps/alex-tavern2-src/` é a cópia extraída do zip original, só como referência local (ignorada).

## Começar um projeto novo

```fish
cp -r ~/git/my/cookiebook/template ~/git/my/meu-projeto
cd ~/git/my/meu-projeto
rm -rf .venv
uv sync
uv run ruff check .; and uv run ruff format --check .; and uv run mypy .; and uv run pytest
```

Depois:

1. Renomeie `name` no `pyproject.toml` e preencha as seções `<!-- PREENCHER -->` do `AGENTS.md`.
2. Escreva o esqueleto do domínio real (contratos, Containers, `run`) com `NotImplementedError` e ensaie com fakes tipados antes de preencher lógica.
3. Adicione cada nova família lógica ao override `disallow_any_expr` do `pyproject.toml`.
4. Remova `notes/` e `roles/summarizer/` quando o domínio real tiver seus próprios exemplos — junto com os testes correspondentes.