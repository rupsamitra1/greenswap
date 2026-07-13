import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../theme.dart';
import '../widgets/duo_button.dart';
import 'results_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _controller = TextEditingController();
  final _api = ApiService();
  bool _loading = false;

  Future<void> _search([String? preset]) async {
    final query = preset ?? _controller.text.trim();
    if (query.isEmpty) return;
    setState(() => _loading = true);
    final result = await _api.analyze(query);
    if (!mounted) return;
    setState(() => _loading = false);
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => ResultsScreen(result: result)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 24),
              // Mascot moment — playful like Duolingo's owl
              const Center(child: Text('🌍', style: TextStyle(fontSize: 72))),
              const SizedBox(height: 12),
              Center(
                child: Text('GreenSwap',
                    style: t.headlineMedium!.copyWith(color: GsColors.green)),
              ),
              const SizedBox(height: 4),
              Center(
                child: Text(
                  'Find a greener version of anything you buy',
                  style: t.bodyMedium!.copyWith(color: GsColors.inkSoft),
                  textAlign: TextAlign.center,
                ),
              ),
              const SizedBox(height: 32),
              // Search box
              Container(
                decoration: BoxDecoration(
                  color: GsColors.bgSoft,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: GsColors.line, width: 2),
                ),
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: TextField(
                  controller: _controller,
                  onSubmitted: (_) => _search(),
                  decoration: const InputDecoration(
                    border: InputBorder.none,
                    hintText: 'Paste a product name or link…',
                    icon: Icon(Icons.search, color: GsColors.inkSoft),
                  ),
                ),
              ),
              const SizedBox(height: 16),
              DuoButton(
                label: _loading ? 'Checking…' : 'Find greener swaps',
                onPressed: _loading ? null : _search,
              ),
              const SizedBox(height: 32),
              Text('Try a demo product', style: t.titleMedium),
              const SizedBox(height: 12),
              _DemoChip(
                emoji: '🧴',
                label: 'Plastic water bottles, 24-pack',
                onTap: () => _search('plastic water bottle'),
              ),
              const SizedBox(height: 10),
              _DemoChip(
                emoji: '🧼',
                label: 'Ultra Dish Soap, 40oz',
                onTap: () => _search('dish soap'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DemoChip extends StatelessWidget {
  final String emoji;
  final String label;
  final VoidCallback onTap;
  const _DemoChip(
      {required this.emoji, required this.label, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(16),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: GsColors.line, width: 2),
          boxShadow: const [
            BoxShadow(color: GsColors.line, offset: Offset(0, 3)),
          ],
        ),
        child: Row(
          children: [
            Text(emoji, style: const TextStyle(fontSize: 22)),
            const SizedBox(width: 12),
            Expanded(
                child:
                    Text(label, style: Theme.of(context).textTheme.titleMedium)),
            const Icon(Icons.chevron_right, color: GsColors.inkSoft),
          ],
        ),
      ),
    );
  }
}
