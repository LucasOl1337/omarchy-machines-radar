# Auditoria: Radar de máquinas v1.0.0

Data: 16/10/2026.

## Base e candidato

Primeiro release. Candidato: `main` deste repositório, sem branches, PRs ou worktrees a integrar.

## Matriz de evidências

| Resultado | Evidência | Validação |
| --- | --- | --- |
| Leitura sem instalar nada nas máquinas | probe.py (stdlib), collect.py `probe` | Coleta real em PC, Hostinger, Sherlocker e Contabo pelo serviço systemd, sem agente SSH |
| Máquina fora mantém a última leitura | collect.py | Teste com host inalcançável: erro registrado, snapshot anterior preservado, arquivo 0600 |
| Limiares e avisos | MachinesModel.js `tone`, `alerts`, `machineView` | Testes Node de limiares, offline local/VPS, serviços agrupados e decodificação `\x2d` |
| Cards, detalhe e Tailnet | Content.qml, Panel.qml | Renderizados numa bancada com dados reais e anonimizados |
| Correspondência máquina ↔ tailnet | collect.py (IP e nome) | Coleta real: lol, Hostinger, Sherlocker e notebook ligados ao aparelho certo |
| Instalação sem QML em cache | install.py | Teste de deploy; geração publicada e lida pelo IPC |

## Validações

`python3 -m unittest discover -s tests`: 5 testes passaram. `node --test tests/test_model.cjs`: 6 testes passaram. `omarchy-plugin-validate .`: passou. `python3 install.py` publicou a geração `60f3c24283397eda7f1e`; o IPC da barra devolveu `version 1.0.0` com as cinco máquinas.

## Agentes e sessões

- Claude Code (Opus 5.5), sessão `066bacdb-c1df-435b-83a5-2cd0aceef22a`: implementação, testes, instalação e publicação.

## Pendências

Nenhuma.
