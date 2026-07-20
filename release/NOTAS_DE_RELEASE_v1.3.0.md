# OpenEmux 1.3.0

Quase tudo aqui nasceu de um único feedback de usuário. Alguém zerou o Aladdin de SNES no OpenEmux e depois escreveu exatamente o que atrapalhou o caminho. Essa lista virou esta release.

## ROMs dentro de arquivos .zip

O scanner reconhece ROMs dentro de arquivos `.zip`. O arquivo continua compactado e é entregue ao RetroArch, que abre nativamente nos cores que carregam a ROM em memória (snes9x, Nestopia, mGBA, Genesis Plus GX e outros). ROMs compactadas aparecem com o nome do arquivo interno, então a busca de capas continua acertando o título real do jogo.

Cores marcados como `needs_fullpath` — os sistemas de mídia em disco (`PS`, `PSP`, `SATURN`, `MCD`, `PCECD`, `GC`) — abrem o caminho por conta própria, então o suporte interno a arquivos compactados do RetroArch não se aplica a eles. Importar um `.zip` para um desses **extrai** o conteúdo, achatando pastas internas para que as referências de faixa de um `.cue` continuem resolvendo, e a importação informa que extraiu em vez de deixar a diferença invisível.

`.7z` não é suportado: exigiria a dependência `py7zr`, que o projeto não distribui.

## Importar ROMs pela interface

- Botões **Importar ROMs** e **Sincronizar capas** na barra superior da janela principal.
- **Arrastar e soltar** ROMs em qualquer ponto da janela, inclusive na tela de biblioteca vazia.
- Pastas são percorridas recursivamente; arquivos compactados são roteados pelo conteúdo interno.
- Duplicatas byte a byte são ignoradas; arquivos diferentes viram `nome (2).ext`.
- Importar a partir da visão **Todos** ou **Favoritos** pergunta em qual console guardar, já com detecção automática selecionada, para que lotes misturados continuem se resolvendo arquivo a arquivo.

## Mapeamento de controle usando o próprio controle

O mapeamento era só por teclado. Agora dá para capturar um comando apertando o botão no controle. A leitura conversa direto com o evdev, sem nenhuma dependência nova, e reproduz a numeração de botões e eixos usada pelo driver `udev` do RetroArch — então o que você mapeia corresponde ao que o emulador enxerga.

**Até quatro portas de gamepad**, cada uma configurada de forma independente e habilitada individualmente. Os hotkeys globais ficam na porta 1: o RetroArch mantém um único conjunto global, então emiti-los a partir da porta 2 sobrescreveria os da porta 1.

Observação: a captura da porta N escuta o N-ésimo controle na ordem de `/dev/input/event*`. Essa ordem casa com a enumeração udev do RetroArch, mas não há garantia de corresponder à atribuição de portas dele. Com menos controles conectados do que a porta escolhida, a captura recusa explicitamente em vez de ler o controle errado.

## Fonte de capas ScreenScraper (opcional)

Uma segunda fonte de capas ao lado das miniaturas do libretro, incluindo a imagem da **label do cartucho**. O caminho do libretro não mudou e continua sendo o padrão.

**Isso exige credenciais para funcionar.** A API v2 do ScreenScraper obriga credenciais de desenvolvedor (`devid`/`devpassword`) em toda requisição; acesso anônimo não existe e o OpenEmux não distribui nenhuma. Cada usuário também precisa da própria conta, senão as requisições consomem uma cota compartilhada muito pequena. A integração está completa e testada, mas inerte até que credenciais sejam fornecidas — por isso vem desligada por padrão.

## O resto

- **A sincronização de capas pode ser interrompida** durante a execução. O cancelamento é verificado entre ROMs e entre URLs candidatas, então parar custa no máximo uma requisição em andamento. As capas já baixadas são mantidas, e as ROMs restantes não são contadas como erro.
- **Barra de dicas** na parte inferior da janela, marcada com 💡, alternando entre atalhos reais derivados dos mapeamentos vigentes. Traduzida para os sete idiomas suportados e desativável em Preferências → Sistema.
- **Alternar tela cheia** virou uma ação remapeável no mapeamento de teclas (`input_toggle_fullscreen`, padrão `F`) em vez de um padrão fixo do RetroArch.
- **Botão direito numa ROM → Mostrar no gerenciador de arquivos**, que seleciona o próprio arquivo pela interface freedesktop FileManager1, em vez de só abrir a pasta.
- **Botão direito num console na barra lateral** oferece reescanear, importar, sincronizar capas e abrir pasta, com escopo naquele console.
- **Ícones dos consoles** nos seletores das Preferências e na página de BIOS.

## Correções

- ROMs compactadas eram indexadas mas descartadas na leitura da playlist, então nunca apareciam na biblioteca e reescanear manualmente não resolvia.
- Listas de console travavam ao rolar: os ícones eram relidos e decodificados do disco a cada renderização de item. Agora são decodificados uma vez para uma textura em cache.
- Os banners de progresso da sincronização de capas e da importação exibiam o contador duas vezes, como `(3/40) (3/40)`.
- A opção mais longa do seletor de fonte de capas ficava cortada e ilegível.

## Downloads

| Pacote | Requisitos |
|---|---|
| AppImage | Qualquer Linux x86_64 |
| `.deb` | Ubuntu 24.04+ / Debian com libadwaita 1.5+ |
| `.rpm` | Fedora 40+ |

Em distribuições mais antigas, use o AppImage.

**Changelog completo:** https://github.com/guilhermefeitosa66/OpenEmux/compare/v1.2.0...v1.3.0
