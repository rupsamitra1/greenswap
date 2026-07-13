import 'package:flutter/material.dart';
import '../models/product.dart';
import '../theme.dart';
import '../widgets/duo_button.dart';
import '../widgets/product_card.dart';

class ResultsScreen extends StatelessWidget {
  final SwapResult result;
  const ResultsScreen({super.key, required this.result});

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final cheaper = result.alternatives
        .where((a) => a.price <= result.original.price)
        .length;
    return Scaffold(
      appBar: AppBar(title: const Text('Greener swaps')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            Text('You were looking at', style: t.titleMedium),
            const SizedBox(height: 10),
            ProductCard(product: result.original),
            const SizedBox(height: 24),
            Row(
              children: [
                Text('Greener swaps ',
                    style: t.titleLarge!.copyWith(color: GsColors.green)),
                const Text('🌱', style: TextStyle(fontSize: 20)),
              ],
            ),
            if (cheaper > 0)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  '$cheaper option${cheaper > 1 ? 's' : ''} at or below the original price',
                  style: t.bodyMedium!.copyWith(color: GsColors.inkSoft),
                ),
              ),
            const SizedBox(height: 12),
            for (final alt in result.alternatives) ...[
              ProductCard(product: alt, highlight: true),
              const SizedBox(height: 12),
            ],
            const SizedBox(height: 8),
            DuoButton(
              label: 'Swap and save the planet',
              onPressed: () => _celebrate(context),
            ),
            const SizedBox(height: 10),
            DuoButton.ghost(
              label: 'Keep original',
              onPressed: () => Navigator.of(context).pop(),
            ),
          ],
        ),
      ),
    );
  }

  void _celebrate(BuildContext context) {
    showDialog(
      context: context,
      builder: (_) => Dialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text('🎉', style: TextStyle(fontSize: 56)),
              const SizedBox(height: 12),
              Text('Great swap!',
                  style: Theme.of(context)
                      .textTheme
                      .titleLarge!
                      .copyWith(color: GsColors.green)),
              const SizedBox(height: 6),
              Text(
                'You just chose a product with a better eco score. Small swaps add up.',
                textAlign: TextAlign.center,
                style: Theme.of(context)
                    .textTheme
                    .bodyMedium!
                    .copyWith(color: GsColors.inkSoft),
              ),
              const SizedBox(height: 18),
              DuoButton(
                label: 'Continue',
                onPressed: () {
                  Navigator.of(context).pop();
                  Navigator.of(context).pop();
                },
              ),
            ],
          ),
        ),
      ),
    );
  }
}
