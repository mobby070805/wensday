import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api_client.dart';
import '../state/app_state.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _name = TextEditingController();
  bool _register = false, _busy = false;
  String? _error;

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final s = context.read<AppState>();
    try {
      if (_register) {
        await s.signUp(_email.text.trim(), _password.text, _name.text.trim());
      } else {
        await s.signIn(_email.text.trim(), _password.text);
      }
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } catch (_) {
      setState(() => _error = "Can't reach the server. Check your connection.");
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text('WENSDAY', style: Theme.of(context).textTheme.headlineMedium?.copyWith(letterSpacing: 4, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 6),
                  const Text('Vanakkam! Your calm, voice-first assistant — Tamil, English & Tanglish.'),
                  const SizedBox(height: 20),
                  if (_register) ...[
                    TextField(controller: _name, decoration: const InputDecoration(labelText: 'Name'), textInputAction: TextInputAction.next),
                    const SizedBox(height: 12),
                  ],
                  TextField(controller: _email, decoration: const InputDecoration(labelText: 'Email'), keyboardType: TextInputType.emailAddress, textInputAction: TextInputAction.next),
                  const SizedBox(height: 12),
                  TextField(controller: _password, decoration: const InputDecoration(labelText: 'Password'), obscureText: true, onSubmitted: (_) => _submit()),
                  if (_error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
                  const SizedBox(height: 16),
                  FilledButton(onPressed: _busy ? null : _submit, child: Text(_register ? 'Create account' : 'Sign in')),
                  TextButton(onPressed: () => setState(() => _register = !_register), child: Text(_register ? 'Have an account? Sign in' : 'New here? Create an account')),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
