# Decisões técnicas, oma-docker

Fatos sobre as escolhas do projeto. Cada decisão diz quem a tomou.

## 1. Motor: SDK Python do Docker (decisão do IAM, vetável)

O app fala com `/var/run/docker.sock` pelo `docker` (docker-py, `APIClient`). O compose é a exceção: roda como subprocesso `docker compose`, porque o SDK não implementa compose. Alternativa descartada: chamar o CLI `docker` para tudo (exigiria interpretar texto de saída).

## 2. Cliente fino e falso (decisão do IAM)

`services/cliente.py` define um protocolo `ClienteDocker`. `ClienteSDK` o implementa com o SDK, `ClienteFalso` (`services/falso.py`) implementa em memória. A interface só conhece o protocolo. O modo `--demo` usa o falso.

## 3. Estrutura da interface (decisão do agente)

Uma tela por vez em `TabbedContent` (8 abas, teclas 1 a 8). Esquema de navegação copiado do omarchy-manager (`ui/navegacao.py`): Ctrl+j/k entre zonas, Ctrl+h/l entre botões, Ctrl+Enter aperta, Ctrl+Espaço ou F1 abre a ajuda, rodapé com no máximo 5 teclas. Ao entrar numa tela sem lista, o foco vai para o primeiro botão, nunca para o campo de filtro (o campo engoliria as teclas de atalho).

## 4. Cores (decisão do agente)

O app lê `~/.local/state/omarchy/current/theme/colors.toml` e monta um tema do Textual. Sem esse arquivo, usa uma paleta escura padrão.

## 5. Atualização (decisão do agente)

Timer de 2 s por aba, que só busca quando a aba está visível e nenhum diálogo está aberto. Chamadas ao Docker rodam em threads daemon. Containers: CPU e memória a cada 4 s, em paralelo (6 threads). Imagens, volumes, redes e limpeza recarregam a cada 6 s, o resumo a cada 6 s.

## 6. Shell em container (decisão do agente)

Abre uma janela do tmux do app com `docker exec -it <id> sh -c 'command -v bash && exec bash || exec sh'`, em vez de abrir uma janela nova do foot. Motivo: segue o mesmo caminho do terminal persistente.

## 7. Abertura e contexto (interpretação do IAM, vetável)

Pedido do JC: "que ficasse escrito OMA DOCKER na tela inicial no terminal, quando abrisse pela primeira vez, e salvasse o contexto mesmo com o app fechado, até o PC desligar". Implementado como: tela de abertura na primeira abertura de cada boot (marcador em `$XDG_RUNTIME_DIR/oma-docker/abertura-mostrada`), e contexto da interface em `estado.json` no mesmo diretório (tmpfs). Fechar o app não apaga. Versão do formato: 1. Arquivo inválido é ignorado.

Dados salvos: aba atual, linha selecionada e filtro de cada aba, alternâncias (só rodando, agrupar, só sem uso), marcados da Limpeza, log em seguimento, formulário aberto e seu rascunho. O tamanho de painéis não é salvo porque não há painéis redimensionáveis.

Segredos: no rascunho do formulário, variáveis cujo nome casa com `pass|senha|secret|token|key|chave|pwd|credential|auth` são descartadas.

## 8. Terminal persistente em tmux (decisão do IAM)

O JC pediu que shell e nvim continuem vivos ao fechar o app. `tmux` existe no PC (`dtach`, `abduco` e `screen` não). O app usa um servidor tmux dedicado (`tmux -S $XDG_RUNTIME_DIR/oma-docker/tmux.sock -f <config embutida>`), isolado do tmux pessoal. `tmux` entra em `depends` do pacote.

## 9. Terminal por `app.suspend()` e não embutido (decisão do agente)

O terminal é o `tmux attach` rodando com o app suspenso (`App.suspend()`), e não um widget de terminal dentro do Textual. Motivo: o nvim roda direto no terminal real, com cores, teclas Ctrl, mouse e redimensionamento do próprio terminal, sem camada de emulação. Teste feito: nvim real dentro do servidor tmux de teste (janela criada, nvim detectado como programa da janela, arquivo aberto na tela capturada, janela e processo vivos depois de "fechar o app"). O widget embutido (`textual-terminal`) não foi testado: o pacote não está nos repositórios do Arch, e a emulação via pyte teria de reproduzir tudo isso.

O anexar com o app suspenso não foi exercitado em terminal interativo real nos testes automáticos (o teste injeta um anexador falso e verifica o comando `tmux attach-session`).

## 10. Segurança (decisão do agente)

Toda remoção passa por `Confirmar`, que lista o que será apagado e o tamanho. O foco inicial é o botão Cancelar. Volume sem uso com dados, ou de tamanho desconhecido, mostra o aviso "Apagar não tem volta". A Limpeza começa sem nada marcado. Containers só são removidos sem `force` pela Limpeza; remoção individual de container rodando avisa que o container será parado à força.

## 11. Testes (decisão do agente)

Três grupos: unitários (modelos, tradução de erros, portas, estado, banner, tmux com socket temporário), de interface com o piloto do Textual contra o cliente falso (teclado e clique), e `-m docker` contra o Docker real (só leitura, mais recursos com rótulo `oma-docker-test=1` criados a partir de `alpine:3.22`). O `addopts` exclui `-m docker` da execução padrão.

## 12. Capturas de tela (decisão do agente)

A tela do notebook (eDP-1) tem 1366x768 e não havia monitor externo ligado, então as capturas têm o tamanho da janela do foot nessa tela (1342x720), não 1620x980. Foram feitas com `--demo`, para não expor dados reais.

## 13. Navegação: Alt nas abas, setas na página (pedido do JC, versão 0.1.1)

Pedido do JC: a navegação do oma-docker parecida com a do omarchy-manager, em que as abas se trocam com Alt e as setas andam pela página. Na 0.1.0, ← → e Alt+h/l trocavam de aba. Na 0.1.1: abas só com Alt+←/→ e Alt+h/l (prioritários, valem com o foco num campo de texto), com as teclas 1 a 8 fora de campos de texto e o clique na aba. As setas sem Alt não trocam de aba: ↑↓ andam pelas fileiras da tela (filtro, botões da barra, lista, botões de ação; na borda da lista o foco passa à fileira vizinha), ←→ e h/l andam entre botões e cartões. No Resumo as setas percorrem a grade de cartões e os botões. Nos diálogos, ←→ e h/l trocam de botão, e no formulário ↑↓ trocam de campo. Por causa do `l` e do `h`, o atalho de logs de container passou de `l` para `o`. O rodapé passou a mostrar `Alt+←/→ Abas`.
