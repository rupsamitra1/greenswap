import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/product.dart';

/// Talks to the Python backend. If the backend isn't running,
/// falls back to demo data so the pitch demo never breaks.
class ApiService {
  static const backendUrl = 'http://localhost:8000'; // change for device demos

  Future<SwapResult> analyze(String query) async {
    try {
      final res = await http
          .post(
            Uri.parse('$backendUrl/analyze'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'query': query}),
          )
          .timeout(const Duration(seconds: 4));
      if (res.statusCode == 200) {
        return SwapResult.fromJson(jsonDecode(res.body));
      }
    } catch (_) {
      // fall through to mock
    }
    return _mock(query);
  }

  SwapResult _mock(String query) {
    final q = query.toLowerCase();
    if (q.contains('bottle') || q.contains('water')) {
      return const SwapResult(
        original: Product(
          id: 'p1',
          name: 'Plastic Water Bottles, 24-pack',
          brand: 'AquaBasic',
          price: 5.99,
          ecoScore: 22,
          trust: TrustLevel.aiEstimated,
          reason: 'Single-use PET plastic; ~24 bottles landfilled per pack.',
          emoji: '🧴',
        ),
        alternatives: [
          Product(
            id: 'a1',
            name: 'Stainless Steel Bottle 24oz',
            brand: 'EverSip',
            price: 9.99,
            ecoScore: 91,
            trust: TrustLevel.certified,
            certification: 'Climate Pledge Friendly',
            reason: 'Reusable; replaces ~150 plastic bottles per year.',
            emoji: '🥤',
          ),
          Product(
            id: 'a2',
            name: 'Glass Bottle with Sleeve',
            brand: 'PureFlow',
            price: 7.49,
            ecoScore: 84,
            trust: TrustLevel.aiEstimated,
            reason: 'Reusable glass; fully recyclable at end of life.',
            emoji: '🫙',
          ),
        ],
      );
    }
    // default demo: dish soap (EPA Safer Choice is real for this category)
    return const SwapResult(
      original: Product(
        id: 'p2',
        name: 'Ultra Dish Soap, 40oz',
        brand: 'SudsMax',
        price: 3.49,
        ecoScore: 38,
        trust: TrustLevel.aiEstimated,
        reason: 'Contains surfactants flagged on the EPA Safer Chemical list.',
        emoji: '🧼',
      ),
      alternatives: [
        Product(
          id: 'a3',
          name: 'Plant-Based Dish Soap, 40oz',
          brand: 'LeafClean',
          price: 3.99,
          ecoScore: 93,
          trust: TrustLevel.certified,
          certification: 'EPA Safer Choice',
          reason: 'All ingredients on the EPA Safer Chemical Ingredients list.',
          emoji: '🌿',
        ),
        Product(
          id: 'a4',
          name: 'Refillable Dish Soap Starter Kit',
          brand: 'ReFill Co.',
          price: 5.25,
          ecoScore: 88,
          trust: TrustLevel.aiEstimated,
          reason: 'Refill pouches cut plastic packaging by ~80%.',
          emoji: '♻️',
        ),
      ],
    );
  }
}
