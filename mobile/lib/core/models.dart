class SpeechSegment {
  const SpeechSegment(this.text, this.lang, this.voice);
  final String text;
  final String lang; // 'ta' | 'en'
  final String voice;

  factory SpeechSegment.fromJson(Map<String, dynamic> j) => SpeechSegment(j['text'] as String, j['lang'] as String, (j['voice'] ?? '') as String);
}

class ChatReply {
  const ChatReply({required this.conversationId, required this.reply, required this.intent, required this.style, required this.tier, required this.speech, required this.data});
  final String conversationId;
  final String reply;
  final String intent;
  final String style; // 'en' | 'tg' | 'ta'
  final String tier; // 'rules' | 'llm' | 'offline'
  final List<SpeechSegment> speech;
  final Map<String, dynamic> data;

  factory ChatReply.fromJson(Map<String, dynamic> j) => ChatReply(
        conversationId: j['conversation_id'] as String,
        reply: j['reply'] as String,
        intent: j['intent'] as String,
        style: j['style'] as String,
        tier: j['tier'] as String,
        speech: [for (final s in (j['speech'] as List? ?? const [])) SpeechSegment.fromJson(s as Map<String, dynamic>)],
        data: (j['data'] as Map?)?.cast<String, dynamic>() ?? const {},
      );
}

class ChatMessage {
  const ChatMessage(this.role, this.text, {this.style, this.tier});
  final String role; // user | assistant | system
  final String text;
  final String? style;
  final String? tier;
}

class TaskItem {
  const TaskItem({required this.id, required this.title, required this.done, required this.priority, this.dueAt});
  final String id;
  final String title;
  final bool done;
  final int priority;
  final DateTime? dueAt;

  factory TaskItem.fromJson(Map<String, dynamic> j) => TaskItem(
        id: j['id'] as String,
        title: j['title'] as String,
        done: j['status'] == 'done',
        priority: (j['priority'] ?? 2) as int,
        dueAt: j['due_at'] == null ? null : DateTime.parse(j['due_at'] as String).toLocal(),
      );
}

class ReminderItem {
  const ReminderItem({required this.id, required this.title, required this.dueAt, required this.recurrence});
  final String id;
  final String title;
  final DateTime dueAt;
  final String recurrence;

  factory ReminderItem.fromJson(Map<String, dynamic> j) => ReminderItem(
        id: j['id'] as String,
        title: j['title'] as String,
        dueAt: DateTime.parse(j['due_at'] as String).toLocal(),
        recurrence: (j['recurrence'] ?? 'none') as String,
      );
}

class NoteItem {
  const NoteItem({required this.id, required this.title, required this.body});
  final String id;
  final String title;
  final String body;

  factory NoteItem.fromJson(Map<String, dynamic> j) => NoteItem(id: j['id'] as String, title: (j['title'] ?? '') as String, body: (j['body'] ?? '') as String);
}

class GoalItem {
  const GoalItem({required this.id, required this.title, required this.progress});
  final String id;
  final String title;
  final int progress;

  factory GoalItem.fromJson(Map<String, dynamic> j) => GoalItem(id: j['id'] as String, title: j['title'] as String, progress: (j['progress'] ?? 0) as int);
}
