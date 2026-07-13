enum TrustLevel { certified, aiEstimated }

class Product {
  final String id;
  final String name;
  final String brand;
  final double price;
  final int ecoScore; // 0–100
  final TrustLevel trust;
  final String? certification; // e.g. "EPA Safer Choice"
  final String reason; // why it's greener / why original scores low
  final String emoji; // playful placeholder instead of images

  const Product({
    required this.id,
    required this.name,
    required this.brand,
    required this.price,
    required this.ecoScore,
    required this.trust,
    this.certification,
    required this.reason,
    required this.emoji,
  });

  factory Product.fromJson(Map<String, dynamic> j) => Product(
        id: j['id'],
        name: j['name'],
        brand: j['brand'],
        price: (j['price'] as num).toDouble(),
        ecoScore: j['eco_score'],
        trust: j['trust'] == 'certified'
            ? TrustLevel.certified
            : TrustLevel.aiEstimated,
        certification: j['certification'],
        reason: j['reason'] ?? '',
        emoji: j['emoji'] ?? '📦',
      );
}

class SwapResult {
  final Product original;
  final List<Product> alternatives;
  const SwapResult({required this.original, required this.alternatives});

  factory SwapResult.fromJson(Map<String, dynamic> j) => SwapResult(
        original: Product.fromJson(j['original']),
        alternatives: (j['alternatives'] as List)
            .map((a) => Product.fromJson(a))
            .toList(),
      );
}
