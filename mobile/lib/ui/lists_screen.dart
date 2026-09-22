import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../core/models.dart';
import '../state/app_state.dart';

enum ListKind { tasks, reminders, notes, goals }

/// One screen for all four collections; it refetches whenever the realtime socket reports a change.
class ListScreen extends StatefulWidget {
  const ListScreen({super.key, required this.kind});
  final ListKind kind;
  @override
  State<ListScreen> createState() => _ListScreenState();
}

class _ListScreenState extends State<ListScreen> {
  List<dynamic> _items = const [];
  bool _loading = true;
  String? _error;
  int _seenTick = -1;
  final _add = TextEditingController();

  String get _path => switch (widget.kind) {
        ListKind.tasks => '/tasks?status=open',
        ListKind.reminders => '/reminders?status=pending',
        ListKind.notes => '/notes',
        ListKind.goals => '/goals',
      };

  Future<void> _load() async {
    final api = context.read<AppState>().api;
    try {
      final raw = await api.get(_path) as List;
      final list = [
        for (final j in raw.cast<Map<String, dynamic>>())
          switch (widget.kind) {
            ListKind.tasks => TaskItem.fromJson(j),
            ListKind.reminders => ReminderItem.fromJson(j),
            ListKind.notes => NoteItem.fromJson(j),
            ListKind.goals => GoalItem.fromJson(j),
          },
      ];
      if (mounted) setState(() {
            _items = list;
            _loading = false;
            _error = null;
          });
    } catch (e) {
      if (mounted) setState(() {
            _loading = false;
            _error = '$e';
          });
    }
  }

  Future<void> _create(String text) async {
    final t = text.trim();
    if (t.isEmpty) return;
    final api = context.read<AppState>().api;
    switch (widget.kind) {
      case ListKind.tasks:
        await api.post('/tasks', {'title': t});
      case ListKind.notes:
        await api.post('/notes', {'body': t});
      case ListKind.goals:
        await api.post('/goals', {'title': t});
      case ListKind.reminders:
        // reminders need a time: use the assistant ("Wensday, nalaiku 9 mani … remind pannu") or pick one here
        final when = await _pickTime();
        if (when == null) return;
        await api.post('/reminders', {'title': t, 'due_at': when.toUtc().toIso8601String()});
    }
    _add.clear();
    await _load();
  }

  Future<DateTime?> _pickTime() async {
    final now = DateTime.now();
    final d = await showDatePicker(context: context, initialDate: now, firstDate: now, lastDate: now.add(const Duration(days: 365)));
    if (d == null || !mounted) return null;
    final t = await showTimePicker(context: context, initialTime: TimeOfDay.fromDateTime(now.add(const Duration(hours: 1))));
    return t == null ? null : DateTime(d.year, d.month, d.day, t.hour, t.minute);
  }

  Future<void> _delete(String id) async {
    final base = switch (widget.kind) {
      ListKind.tasks => '/tasks',
      ListKind.reminders => '/reminders',
      ListKind.notes => '/notes',
      ListKind.goals => '/goals',
    };
    await context.read<AppState>().api.delete('$base/$id');
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final tick = context.watch<AppState>().syncTick;
    if (tick != _seenTick) {
      _seenTick = tick;
      WidgetsBinding.instance.addPostFrameCallback((_) => _load());
    }
    return Column(children: [
      Padding(
        padding: const EdgeInsets.all(12),
        child: Row(children: [
          Expanded(child: TextField(controller: _add, decoration: InputDecoration(hintText: 'Add ${widget.kind.name.replaceAll(RegExp(r's$'), '')}…', border: const OutlineInputBorder()), onSubmitted: _create)),
          const SizedBox(width: 8),
          IconButton.filled(onPressed: () => _create(_add.text), icon: const Icon(Icons.add), tooltip: 'Add'),
        ]),
      ),
      if (_error != null) Padding(padding: const EdgeInsets.all(8), child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
      Expanded(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _items.isEmpty
                ? const Center(child: Text('Nothing here yet.'))
                : RefreshIndicator(
                    onRefresh: _load,
                    child: ListView.separated(
                      itemCount: _items.length,
                      separatorBuilder: (_, __) => const Divider(height: 1),
                      itemBuilder: (_, i) => _tile(_items[i]),
                    ),
                  ),
      ),
    ]);
  }

  Widget _tile(dynamic item) {
    final fmt = DateFormat('EEE d MMM, h:mm a');
    return switch (item) {
      TaskItem t => CheckboxListTile(
          value: t.done,
          title: Text(t.title),
          subtitle: t.dueAt == null ? null : Text(fmt.format(t.dueAt!)),
          secondary: IconButton(icon: const Icon(Icons.delete_outline), tooltip: 'Delete', onPressed: () => _delete(t.id)),
          onChanged: (_) async {
            await context.read<AppState>().api.patch('/tasks/${t.id}', {'status': t.done ? 'open' : 'done'});
            await _load();
          },
        ),
      ReminderItem r => ListTile(title: Text(r.title), subtitle: Text('${fmt.format(r.dueAt)}${r.recurrence == 'none' ? '' : ' · ${r.recurrence}'}'), trailing: IconButton(icon: const Icon(Icons.close), tooltip: 'Cancel', onPressed: () => _delete(r.id))),
      NoteItem n => ListTile(title: Text(n.title.isEmpty ? 'Note' : n.title), subtitle: Text(n.body, maxLines: 3, overflow: TextOverflow.ellipsis), trailing: IconButton(icon: const Icon(Icons.delete_outline), tooltip: 'Delete', onPressed: () => _delete(n.id))),
      GoalItem g => ListTile(
          title: Text(g.title),
          subtitle: Padding(padding: const EdgeInsets.only(top: 6), child: LinearProgressIndicator(value: g.progress / 100)),
          trailing: Text('${g.progress}%'),
          onLongPress: () => _delete(g.id),
        ),
      _ => const SizedBox.shrink(),
    };
  }
}
