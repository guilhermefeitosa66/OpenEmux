# Phase 08 — Refatoração da UI para o GNOME HIG

> **Objetivo:** adequar toda a interface do Opemux às *GNOME Human Interface
> Guidelines* (HIG) atuais e ao design language Adwaita/libadwaita, preservando
> a identidade e a experiência do OpenEmu (grade de capas por console, foco na
> biblioteca, navegação leve) — mas nativa do GNOME/Linux em vez de macOS.

Status: **planejado** · Escopo: `src/opemux/ui/*` · Sem mudanças na `core/`.

---

## 1. Princípios norteadores

1. **HIG-first, OpenEmu-in-spirit.** O OpenEmu é um app macOS: sidebar de
   coleções, grade de capas grande, toolbar no topo. Reproduzimos a *sensação*
   (biblioteca centrada em capas, navegação por console) usando os padrões
   nativos do GNOME, não imitando o chrome do macOS.
2. **Usar libadwaita, não reinventar.** Toda estrutura que hoje é montada à mão
   com `Gtk.Box` + CSS deve migrar para widgets Adwaita equivalentes
   (`AdwNavigationSplitView`, `AdwPreferencesPage`, `AdwActionRow`, etc.), que já
   trazem espaçamento, tipografia, dark mode, foco e comportamento adaptativo
   corretos.
3. **Adaptatividade e acessibilidade não são opcionais.** Layout colapsável,
   navegação por teclado, foco visível e contraste corretos por padrão.
4. **Não tocar na lógica de `core/`.** A refatoração é de apresentação; os
   contratos (`refresh_library`, callbacks de launch/cover/input) permanecem.

### Referências GNOME (consultadas)

- GNOME HIG — índice de guidelines e patterns: <https://developer.gnome.org/hig/guidelines.html>
- Sidebars / navigation split view: <https://developer.gnome.org/hig/patterns/nav/sidebars.html>
- Boxed lists / preferences rows: <https://developer.gnome.org/hig/patterns/containers/boxed-lists.html>
- UI styling: <https://developer.gnome.org/hig/guidelines/ui-styling.html>
- Selection & edit modes: <https://developer.gnome.org/hig/patterns/containers/selection-mode.html>
- libadwaita implementa os patterns do HIG; usar o **Adwaita Demo** como
  referência viva de widgets.

Notas relevantes das guidelines:

- **Sidebar** → usar `AdwNavigationSplitView`; controles que afetam a lista ficam
  **acima** dela (no header bar do painel); ordenar pela utilidade ao usuário.
- **Boxed lists** → preferências em `AdwPreferencesGroup` com rows prontos
  (`AdwActionRow`, `AdwComboRow`, `AdwSwitchRow`, `AdwEntryRow`, `AdwSpinRow`,
  `AdwExpanderRow`); **no máximo 1 controle por row** (2 em casos extremos);
  o controle é focável, não a row inteira.
- **Feedback** → toasts/banners/diálogos para estados transitórios; o GNOME
  **não usa status bar** no rodapé.
- **GNOME 48+** usa Adwaita Sans (default) e Adwaita Mono; evitar fixar fontes.

---

## 2. Diagnóstico da UI atual (gaps vs. HIG)

| Área | Estado atual | Gap vs. HIG |
|------|--------------|-------------|
| **Shell da janela** | `Adw.ApplicationWindow` → `ToastOverlay` → `Gtk.Box` horizontal montado à mão (`sidebar` + `Gtk.Separator` + `content_box`) (`window.py:100-136`) | Não usa `AdwNavigationSplitView`/`AdwOverlaySplitView`; separador manual; não colapsa em telas estreitas |
| **Sidebar** | `Gtk.Box` de 360px fixo com `.sidebar` CSS + `Gtk.ListBox` + botão "pill" de settings no rodapé (`window.py:464-507`) | Deveria ser o painel de um split view com header bar próprio; largura fixa não-adaptativa; settings deveria sair da sidebar |
| **Header bar** | `Adw.HeaderBar` com `Gtk.SearchEntry` como *title widget* sempre visível (`window.py:210-229`) | Search sempre no lugar do título; sem título/subtítulo de view; sem menu primário (hambúrguer) |
| **Menu primário** | Inexistente | HIG exige menu com Preferências, Atalhos de teclado, Sobre |
| **Settings** | Grade de cards custom (`SettingsGrid`/`SettingsCard` = `Gtk.FlowBox` de botões) que trocam views dentro do `Adw.ViewStack` principal (`settings_grid.py`, `window.py:687-1076`) | Deveria ser `AdwPreferencesDialog`/`AdwPreferencesWindow` com `AdwPreferencesPage`/`Group`/rows |
| **Status bar** | Barra custom no rodapé com spinner + label + `Gtk.ProgressBar` (`window.py:374-462`) | GNOME não usa status bar; progresso deve ir a toast/banner ou indicador no header |
| **Menu de contexto do ROM** | `Gtk.Popover` montado à mão com `Gtk.Button`s (`grid.py:283-377`) | Deveria ser `Gio.Menu` + `Gtk.PopoverMenu` com `Gio.Action` |
| **Grade de ROMs** | `Gtk.FlowBox` de `RomItem` (`Gtk.Box` custom com overlay, hover translateY via CSS) (`grid.py`) | Aceitável, mas hover/elevação deve usar `.card`; falta estado vazio (`AdwStatusPage`) e modo de seleção |
| **Dropdowns** | `Gtk.DropDown` com `SignalListItemFactory` custom para idioma e console (`window.py:231-372`) | Migrar para `AdwComboRow` dentro das preferências onde aplicável |
| **First boot** | `Gtk.Label`+`Spinner`+`ProgressBar` em `Gtk.Box` (`first_boot_window.py`) | Usar `AdwStatusPage` + `AdwToolbarView`; header bar vazio |
| **Tipografia/CSS** | `style.css` com `.heading` custom, sombras hardcoded, `transform: translateY` no hover | Usar style classes do Adwaita (`.title-1/2/4`, `.dim-label`, `.card`, `.caption`); cores nomeadas `@…_color` (já usa em parte) |

---

## 3. Arquitetura-alvo da UI

```
Adw.ApplicationWindow
└── Adw.ToastOverlay
    └── Adw.NavigationSplitView              (colapsável; breakpoint via AdwBreakpoint)
        ├── sidebar: Adw.NavigationPage
        │   └── Adw.ToolbarView
        │       ├── [top] Adw.HeaderBar
        │       │        ├── title: "Biblioteca"
        │       │        └── [end] botão de busca (toggle) + menu primário (☰)
        │       └── content: Gtk.ScrolledWindow
        │                    └── Gtk.ListBox (.navigation-sidebar)
        │                        ├── seção BIBLIOTECA: Todos, Favoritos
        │                        └── seção CONSOLES: <um row por console detectado>
        │
        └── content: Adw.NavigationPage
            └── Adw.ToolbarView
                ├── [top] Adw.HeaderBar
                │        ├── [start] botão voltar (quando colapsado)
                │        ├── title: nome do console + Adw.WindowTitle (subtítulo = nº de jogos)
                │        └── [end] Parar (durante jogo) · Atualizar · (busca)
                ├── [top] Gtk.SearchBar  (revelada pelo toggle; contém Gtk.SearchEntry)
                └── content: Adw.ViewStack
                             ├── página "grid": Gtk.ScrolledWindow → RomGrid (Gtk.FlowBox)
                             └── página "empty": Adw.StatusPage (biblioteca vazia)

Preferências (fora do split view):
Adw.PreferencesDialog  (aberto pelo menu primário → "Preferências")
├── AdwPreferencesPage "ROMs & Biblioteca"   → grupos com AdwActionRow/EntryRow
├── AdwPreferencesPage "BIOS"                → AdwExpanderRow por console
├── AdwPreferencesPage "Controles"           → captura de input
├── AdwPreferencesPage "Vídeo/Shaders"       → AdwComboRow por console
└── AdwPreferencesPage "Sistema"             → idioma (AdwComboRow), sobre RetroArch

First boot:
Adw.Window → Adw.ToolbarView (header vazio) → Adw.StatusPage (ícone + título +
progresso) — ou Adw.Dialog sobre a janela principal.
```

### Feedback (substituindo a status bar)

- Tarefas rápidas / conclusões → `Adw.Toast` (já existe o `ToastOverlay`).
- Operações longas com progresso (scan, download de capas) → `Adw.Banner`
  revelável no topo do content, com `Gtk.ProgressBar` embutido, **ou** um
  `Gtk.Spinner`/progresso compacto empacotado no header bar enquanto ativo.
- Remover completamente `.status-bar` e `_build_status_bar`, migrando
  `_begin_task/_update_task/_finish_task` para atualizar o banner/toast.

---

## 4. Plano de refatoração em fases incrementais

Cada etapa deve deixar o app **executável e testável** (`make run`), commitada
isoladamente (`refactor:`/`feat:` conforme a convenção do projeto).

### Etapa 1 — Shell com NavigationSplitView + ToolbarView
- Substituir `main_box`/`Gtk.Separator`/`content_box` por
  `Adw.NavigationSplitView` com dois `Adw.NavigationPage` + `Adw.ToolbarView`.
- Mover header bars para dentro de cada `ToolbarView`.
- Adicionar `Adw.Breakpoint` (`max-width: 550sp`) para colapsar a sidebar e
  mostrar botão de voltar.
- **Sem** mudança de comportamento de dados; `content_stack` continua existindo
  dentro do content page.

### Etapa 2 — Header bar + busca + menu primário
- Remover `SearchEntry` do title widget. Título passa a `Adw.WindowTitle`
  (nome do console + subtítulo com contagem).
- Adicionar botão de busca (`system-search-symbolic`, toggle) que revela um
  `Gtk.SearchBar` sob o header; ligar ao `_on_search_changed`.
- Adicionar `Gtk.MenuButton` (`open-menu-symbolic`) com `Gio.Menu`:
  Preferências · Atalhos de teclado · Sobre o Opemux.
- Criar `Gtk.ShortcutsWindow` e `Adw.AboutDialog` (metadados do app).

### Etapa 3 — Sidebar como painel do split view
- Header bar próprio no painel da sidebar com título "Biblioteca".
- `Gtk.ListBox` com `.navigation-sidebar` (manter), organizado em seções
  (Biblioteca: Todos/Favoritos; Consoles: …) — usar rows com ícone + label.
- Remover o botão "pill" de settings do rodapé (settings passa ao menu primário).
- Remover largura fixa 360px → deixar `AdwNavigationSplitView` gerenciar
  (`sidebar-width-fraction` / `min-sidebar-width`).

### Etapa 4 — Preferências em AdwPreferencesDialog
- Criar `ui/preferences.py` com `Adw.PreferencesDialog` e uma
  `AdwPreferencesPage` por área (ROMs, BIOS, Controles, Shaders, Sistema).
- Converter cada tela custom de settings:
  - **ROMs:** `AdwActionRow` com caminho + botão "Escolher pasta"; ações de
    rescan/sync como rows com sufixo botão.
  - **BIOS:** um `AdwExpanderRow` por console, cada arquivo como `AdwActionRow`
    com ícone de status (ok/missing) — substitui `.bios-group` custom.
  - **Controles:** manter a captura de tecla, mas apresentar bindings como
    `AdwActionRow` com botão de atalho no sufixo; console/dispositivo em
    `AdwComboRow`.
  - **Shaders:** `AdwComboRow` por console (substitui `_build_shader_dropdown`);
    switch "renderizar cartucho" vira `AdwSwitchRow`.
  - **Sistema:** idioma em `AdwComboRow` (substitui `_build_language_dropdown`);
    infos do RetroArch em `AdwActionRow`/`AdwPropertyRow`.
- Remover `settings_grid.py` (`SettingsGrid`/`SettingsCard`) e todos os
  `_open_settings_*` que trocavam view; o `content_stack` deixa de ter páginas
  de settings.

### Etapa 5 — Menu de contexto do ROM via Gio.Action
- Trocar o popover manual (`grid.py:283-377`) por `Gtk.PopoverMenu.new_from_model`
  com um `Gio.Menu` (Favoritar/Desfavoritar, Escolher capa, Remover capa).
- Expor as ações via `Gio.SimpleActionGroup` no `RomItem` (ou ações da janela
  com parâmetro), com estado (favorito) refletido no menu.

### Etapa 6 — Estados vazios, banner de progresso e limpeza de CSS
- Adicionar página `Adw.StatusPage` no `content_stack` para biblioteca/console
  vazio ("Nenhum jogo encontrado" + ação "Escolher pasta de ROMs").
- Remover a status bar; migrar progresso para `Adw.Banner`/toast.
- Enxugar `style.css`: trocar `.rom-card-hover` (translateY + sombra) por `.card`
  + estados do Adwaita; remover `.heading`/`.status-bar`/`.settings-card*`
  agora órfãos; manter só o que é específico (frame de cartucho, badge de
  favorito, placeholder de capa).

---

## 5. Mapeamento widget-a-widget (de → para)

| Hoje | Alvo |
|------|------|
| `Gtk.Box` horizontal + `Gtk.Separator` (`window.py:100-136`) | `Adw.NavigationSplitView` |
| `content_box` `Gtk.Box` vertical | `Adw.NavigationPage` → `Adw.ToolbarView` |
| `SearchEntry` como title widget | `Adw.WindowTitle` + `Gtk.SearchBar` toggle |
| — (sem menu) | `Gtk.MenuButton` + `Gio.Menu` (Preferências/Atalhos/Sobre) |
| `_build_status_bar` + `_refresh_status_bar` | `Adw.Banner`/`Adw.Toast` |
| `SettingsGrid`/`SettingsCard` (`settings_grid.py`) | `Adw.PreferencesDialog` + `AdwPreferencesPage/Group` |
| `_build_language_dropdown` (factory custom) | `AdwComboRow` (página Sistema) |
| `_build_shader_dropdown` | `AdwComboRow` (página Shaders) |
| `_on_toggle_render_cartridge` (botão) | `AdwSwitchRow` |
| `.bios-group` custom | `AdwExpanderRow` + `AdwActionRow` |
| Popover manual do ROM (`grid.py:283-377`) | `Gtk.PopoverMenu` + `Gio.Menu`/`Gio.Action` |
| Hover `transform: translateY` | style class `.card` + realce Adwaita |
| `FirstBootWindow` (`Gtk.Label`/`ProgressBar`) | `Adw.ToolbarView` + `Adw.StatusPage` |

---

## 6. Tipografia, estilo e cores

- Usar style classes do Adwaita em vez de CSS ad-hoc: `.title-1`/`.title-2`/
  `.title-4`, `.heading`, `.dim-label`, `.caption`, `.card`, `.pill` (nativos).
- Não fixar família de fonte — respeitar Adwaita Sans/Mono do sistema (GNOME 48+).
- Continuar usando cores nomeadas (`@window_bg_color`, `@accent_bg_color`,
  `@card_bg_color`…) para dark mode automático; **remover** cores hardcoded como
  `#2f9e44`/`#d94841` → usar `.success`/`.error`/`.warning` (ex.: status de BIOS).
- Ícones sempre `-symbolic` no chrome (já é o caso majoritariamente).
- `style.css` final deve conter só regras que o Adwaita não cobre (frame de
  cartucho posicionado, badge de favorito, placeholder de capa).

---

## 7. Adaptatividade e acessibilidade

- `Adw.Breakpoint` para colapsar a sidebar (single-pane + botão voltar) abaixo de
  ~550sp; a grade de capas já é `FlowBox` fluida.
- Navegação por teclado: rows/controles focáveis (garantido pelos widgets
  Adwaita); menu primário e busca acionáveis por atalho (`Ctrl+F`, `Ctrl+,`).
- Foco visível e contraste herdados do Adwaita ao remover o CSS custom de hover.
- Tooltips e labels acessíveis mantidos; validar com o padrão de a11y do GNOME.

---

## 8. Riscos e mitigação

- **`window.py` é grande (~2000 linhas) e concentra tudo.** Extrair Preferências
  para `ui/preferences.py` e (opcional) sidebar para `ui/sidebar.py` reduz risco
  e facilita revisão por etapa.
- **Versão do libadwaita.** `AdwPreferencesDialog`/`AdwNavigationSplitView`/
  `AdwBreakpoint` exigem libadwaita ≥ 1.4/1.5. Confirmar a versão empacotada no
  AppImage vendorizado; se antiga, usar fallbacks (`AdwLeaflet`/
  `AdwPreferencesWindow`) ou atualizar o runtime.
- **Regressões de comportamento.** Manter os contratos de `core/` e cobrir com os
  testes existentes (`tests/`) + validação manual via `make run` a cada etapa.
- **i18n.** Toda string nova passa por `tr()`; adicionar chaves aos JSON de
  `i18n/locales/` (menu primário, títulos de páginas de preferências, estados
  vazios).

---

## 9. Checklist de conclusão

- [x] Shell usa `AdwNavigationSplitView` + `AdwToolbarView`, colapsável (`AdwBreakpoint` em `max-width: 550sp`).
- [x] Header bar com título de view (`AdwWindowTitle`), busca em `Gtk.SearchBar` e menu primário.
- [x] Menu primário com Preferências, Atalhos de teclado e Sobre (`AdwAboutDialog` + `Gtk.ShortcutsWindow`, acels `Ctrl+,` / `Ctrl+F` / `Ctrl+?`).
- [x] Todas as configurações em `AdwPreferencesDialog` com rows Adwaita (`ui/preferences.py`).
- [x] `settings_grid.py` e a status bar removidos.
- [x] Menu de contexto do ROM via `Gio.Menu`/`Gtk.PopoverMenu` + `Gio.Action`.
- [x] Estados vazios com `AdwStatusPage`; progresso via `AdwBanner`/toast.
- [x] `first_boot_window` usando `AdwStatusPage` + `AdwToolbarView`.
- [x] `style.css` enxuto; cores de status BIOS agora usam `.success`/`.warning` (removidos `#2f9e44`/`#d94841`).
- [x] Testes verdes (`python -m unittest discover -s tests` → 56 OK); UI validada por smoke test headless usando os typelibs do `AppDir` (o `.venv` não traz PyGObject/GTK4). `make run` depende do ambiente com GI do GTK4.

> **Nota de verificação:** o `make run` da máquina de dev não roda direto porque
> o `.venv` não inclui PyGObject/GTK4 e o typelib do GTK4 não está no path padrão
> do sistema. A construção real de `OpemuxWindow`, do `OpemuxPreferences` e da
> `FirstBootWindow` foi exercitada por smoke tests sobre os typelibs empacotados
> em `AppDir/` (Adw 1.5.0 / GTK 4.14.5), sem `CRITICAL`/`WARNING`.
