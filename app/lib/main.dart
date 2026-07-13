import 'package:flutter/material.dart';
import 'screens/home_screen.dart';
import 'theme.dart';

// Supabase setup (uncomment when you have your project keys):
// import 'package:supabase_flutter/supabase_flutter.dart';
//
// Future<void> initSupabase() async {
//   await Supabase.initialize(
//     url: 'YOUR_SUPABASE_URL',
//     anonKey: 'YOUR_SUPABASE_ANON_KEY',
//   );
// }

void main() {
  // await initSupabase();
  runApp(const GreenSwapApp());
}

class GreenSwapApp extends StatelessWidget {
  const GreenSwapApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'GreenSwap',
      debugShowCheckedModeBanner: false,
      theme: gsTheme(),
      home: const HomeScreen(),
    );
  }
}
