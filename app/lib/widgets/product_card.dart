import 'package:flutter/material.dart';
import '../models/product.dart';
import '../theme.dart';

Color ecoColor(int score) {
  if (score >= 70) return GsColors.green;
  if (score >= 40) return GsColors.orange;
  return GsColors.red;
}

class ProductCard extends StatelessWidget {
  final Product product;
  final bool highlight; // green border for suggested swaps
  const ProductCard({super.key, required this.product, this.highlight = false});

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(
          color: highlight ? GsColors.green : GsColors.line,
          width: 2,
        ),
        boxShadow: [
          BoxShadow(
            color: highlight ? GsColors.greenDark : GsColors.line,
            offset: const Offset(0, 3),
          ),
        ],
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Emoji "image" tile
          Container(
            width: 56,
            height: 56,
            decoration: BoxDecoration(
              color: GsColors.bgSoft,
              borderRadius: BorderRadius.circular(14),
            ),
            alignment: Alignment.center,
            child: Text(product.emoji, style: const TextStyle(fontSize: 28)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(product.name, style: t.titleMedium),
                Text(product.brand,
                    style: t.bodyMedium!.copyWith(color: GsColors.inkSoft)),
                const SizedBox(height: 6),
                Row(
                  children: [
                    Text('\$${product.price.toStringAsFixed(2)}',
                        style: t.titleMedium!.copyWith(color: GsColors.blue)),
                    const SizedBox(width: 10),
                    _TrustBadge(product: product),
                  ],
                ),
                const SizedBox(height: 6),
                Text(product.reason,
                    style: t.bodyMedium!
                        .copyWith(color: GsColors.inkSoft, fontSize: 13)),
              ],
            ),
          ),
          const SizedBox(width: 8),
          _ScoreRing(score: product.ecoScore),
        ],
      ),
    );
  }
}

class _ScoreRing extends StatelessWidget {
  final int score;
  const _ScoreRing({required this.score});

  @override
  Widget build(BuildContext context) {
    final color = ecoColor(score);
    return SizedBox(
      width: 48,
      height: 48,
      child: Stack(
        alignment: Alignment.center,
        children: [
          CircularProgressIndicator(
            value: score / 100,
            strokeWidth: 5,
            backgroundColor: GsColors.line,
            valueColor: AlwaysStoppedAnimation(color),
          ),
          Text('$score',
              style: TextStyle(
                  fontWeight: FontWeight.w800, fontSize: 14, color: color)),
        ],
      ),
    );
  }
}

class _TrustBadge extends StatelessWidget {
  final Product product;
  const _TrustBadge({required this.product});

  @override
  Widget build(BuildContext context) {
    final certified = product.trust == TrustLevel.certified;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: certified
            ? GsColors.gold.withOpacity(0.18)
            : GsColors.blue.withOpacity(0.12),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(
        certified ? '★ ${product.certification ?? "Certified"}' : 'AI estimate',
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w800,
          color: certified ? const Color(0xFF9A7B00) : GsColors.blueDark,
        ),
      ),
    );
  }
}
