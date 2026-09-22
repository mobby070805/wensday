import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/app_state.dart';
import 'lists_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _tab = 0;
  final _text = TextEditingController();
  final _scroll = ScrollController();

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final pages = <Widget>[
      _assistant(s),
      const ListScreen(kind: ListKind.tasks),
      const ListScreen(kind: ListKind.reminders),
      const ListScreen(kind: ListKind.notes),
      const ListScreen(kind: ListKind.goals),
    ];
    return Scaffold(
      appBar: AppBar(
        title: const Text('WENSDAY', style: TextStyle(letterSpacing: 3, fontWeight: FontWeight.w700)),
        actions: [
          if (s.queued > 0) Padding(padding: const EdgeInsets.symmetric(horizontal: 8), child: Center(child: Text('${s.queued} queued'))),
          Icon(Icons.circle, size: 10, color: s.connected ? Colors.greenAccent : Colors.redAccent, semanticLabel: s.connected ? 'Connected' : 'Reconnecting'),
          PopupMenuButton<String>(
            onSelected: (v) => v == 'out' ? s.signOut() : s.setMuted(!s.muted),
            itemBuilder: (_) => [PopupMenuItem(value: 'mute', child: Text(s.muted ? 'Unmute voice' : 'Mute voice')), const PopupMenuItem(value: 'out', child: Text('Sign out'))],
          ),
        ],
      ),
      body: IndexedStack(index: _tab, children: pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.graphic_eq), label: 'Assistant'),
          NavigationDestination(icon: Icon(Icons.check_circle_outline), label: 'Tasks'),
          NavigationDestination(icon: Icon(Icons.alarm), label: 'Reminders'),
          NavigationDestination(icon: Icon(Icons.note_outlined), label: 'Notes'),
          NavigationDestination(icon: Icon(Icons.flag_outlined), label: 'Goals'),
        ],
      ),
    );
  }

  Widget _assistant(AppState s) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) _scroll.animateTo(_scroll.position.maxScrollExtent, duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
    });
    final label = switch (s.voiceState) {
      VoiceState.idle => 'Tap to speak',
      VoiceState.listening => 'Listening…',
      VoiceState.thinking => 'Thinking…',
      VoiceState.speaking => 'Speaking… tap to interrupt',
    };
    final scheme = Theme.of(context).colorScheme;
    final orbColor = switch (s.voiceState) {
      VoiceState.listening => Colors.amber,
      VoiceState.thinking => Colors.blueAccent,
      _ => scheme.primary,
    };
    return Column(
      children: [
        Expanded(
          child: ListView.builder(
            controller: _scroll,
            padding: const EdgeInsets.all(12),
            itemCount: s.messages.length + (s.messages.isEmpty ? 1 : 0),
            itemBuilder: (_, i) {
              if (s.messages.isEmpty) return const Padding(padding: EdgeInsets.all(24), child: Text('Try: “Wensday, nalaiku 9 mani meeting remind pannu.”', textAlign: TextAlign.center));
              final m = s.messages[i];
              final mine = m.role == 'user';
              return Align(
                alignment: mine ? Alignment.centerRight : (m.role == 'system' ? Alignment.center : Alignment.centerLeft),
                child: Container(
                  margin: const EdgeInsets.symmetric(vertical: 4),
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                  constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.82),
                  decoration: BoxDecoration(
                    color: mine ? Colors.blueAccent.withValues(alpha: 0.2) : (m.role == 'system' ? Colors.amber.withValues(alpha: 0.14) : scheme.primary.withValues(alpha: 0.12)),
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Text(m.text),
                ),
              );
            },
          ),
        ),
        if (s.error != null) Padding(padding: const EdgeInsets.all(8), child: Text(s.error!, style: TextStyle(color: scheme.error))),
        if (s.partial.isNotEmpty) Padding(padding: const EdgeInsets.all(4), child: Text(s.partial, style: TextStyle(color: scheme.primary, fontStyle: FontStyle.italic))),
        Semantics(
          button: true,
          label: label,
          child: GestureDetector(
            onTap: s.toggleListening,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 250),
              width: s.voiceState == VoiceState.idle ? 88 : 104,
              height: s.voiceState == VoiceState.idle ? 88 : 104,
              decoration: BoxDecoration(shape: BoxShape.circle, color: orbColor, boxShadow: [BoxShadow(color: orbColor.withValues(alpha: 0.5), blurRadius: 28)]),
              child: const Icon(Icons.mic, size: 38, color: Colors.black87),
            ),
          ),
        ),
        Padding(padding: const EdgeInsets.only(top: 6), child: Text(label)),
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
          child: Row(children: [
            Expanded(
              child: TextField(
                controller: _text,
                decoration: const InputDecoration(hintText: 'Type in Tamil, English or Tanglish…', border: OutlineInputBorder()),
                onSubmitted: (v) {
                  s.send(v);
                  _text.clear();
                },
              ),
            ),
            const SizedBox(width: 8),
            IconButton.filled(
              onPressed: () {
                s.send(_text.text);
                _text.clear();
              },
              icon: const Icon(Icons.send),
              tooltip: 'Send',
            ),
          ]),
        ),
      ],
    );
  }
}
