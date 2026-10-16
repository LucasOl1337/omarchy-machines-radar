# Auditoria: Radar de máquinas v1.0.1

Data: 16/10/2026.

## Base e candidato

Base: tag `v1.0.0`. Candidato: commit desta correção na `main`, sem branches, PRs ou worktrees a integrar.

## Matriz de evidências

| Resultado | Evidência | Validação |
| --- | --- | --- |
| Imagens em loop contam como reservado | probe.py `loop_images`, `disks` (`reserved`, `holds`, `image`) | Probe na Contabo: raiz com 660 GB reservados pra `/home/lucas` e `/home/alonso`; PC sem loops segue igual |
| Porcentagem e alarme só da parte do sistema | MachinesModel.js `diskUse`, `diskDetail`, `metrics`, `alerts` | Teste Node da VPS dividida (67%, verde, sem aviso); card renderizado numa bancada |
| Detalhe dos discos | Content.qml | Bancada: raiz e as duas imagens com uso próprio |

## Validações

`python3 -m unittest discover -s tests`: 5 testes passaram. `node --test tests/test_model.cjs`: 7 testes passaram. `omarchy-plugin-validate .`: passou. `python3 install.py` publicou a nova geração e o IPC da barra devolveu a Contabo em `yellow` (só serviços falhando) em vez de `red`.

## Agentes e sessões

- Claude Code (Opus 5.5), sessão `066bacdb-c1df-435b-83a5-2cd0aceef22a`.

## Pendências

Nenhuma.
