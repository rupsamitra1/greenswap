import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// GreenSwap design tokens — Duolingo-style: bold, rounded, playful.
/// Primary = leaf green, secondary = sky blue.
class GsColors {
  static const green = Color(0xFF43C000); // primary action
  static const greenDark = Color(0xFF369B00); // 3D button bottom edge
  static const blue = Color(0xFF1CB0F6); // secondary action / links
  static const blueDark = Color(0xFF1899D6);
  static const ink = Color(0xFF3C3C3C); // main text
  static const inkSoft = Color(0xFF777777); // secondary text
  static const line = Color(0xFFE5E5E5); // card borders
  static const bg = Color(0xFFFFFFFF);
  static const bgSoft = Color(0xFFF7F7F7);
  static const gold = Color(0xFFFFC800); // certified badge
  static const red = Color(0xFFFF4B4B); // low eco score
  static const orange = Color(0xFFFF9600); // medium eco score
}

ThemeData gsTheme() {
  final base = ThemeData(useMaterial3: true, scaffoldBackgroundColor: GsColors.bg);
  final text = GoogleFonts.nunitoTextTheme(base.textTheme).apply(
    bodyColor: GsColors.ink,
    displayColor: GsColors.ink,
  );
  return base.copyWith(
    textTheme: text.copyWith(
      headlineMedium: GoogleFonts.nunito(
          fontWeight: FontWeight.w800, fontSize: 26, color: GsColors.ink),
      titleLarge: GoogleFonts.nunito(
          fontWeight: FontWeight.w800, fontSize: 20, color: GsColors.ink),
      titleMedium: GoogleFonts.nunito(
          fontWeight: FontWeight.w700, fontSize: 16, color: GsColors.ink),
      bodyMedium: GoogleFonts.nunito(fontSize: 15, color: GsColors.ink),
      labelLarge: GoogleFonts.nunito(
          fontWeight: FontWeight.w800, fontSize: 15, letterSpacing: 0.8),
    ),
    colorScheme: base.colorScheme.copyWith(
      primary: GsColors.green,
      secondary: GsColors.blue,
    ),
    appBarTheme: AppBarTheme(
      backgroundColor: GsColors.bg,
      elevation: 0,
      centerTitle: true,
      titleTextStyle: GoogleFonts.nunito(
          fontWeight: FontWeight.w800, fontSize: 18, color: GsColors.ink),
      iconTheme: const IconThemeData(color: GsColors.inkSoft),
    ),
  );
}
