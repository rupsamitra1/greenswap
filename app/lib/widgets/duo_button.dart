import 'package:flutter/material.dart';
import '../theme.dart';

/// The signature Duolingo-style button: chunky, rounded, with a hard
/// bottom edge that "presses down" on tap.
class DuoButton extends StatefulWidget {
  final String label;
  final VoidCallback? onPressed;
  final Color color;
  final Color edgeColor;
  final Color textColor;
  final bool outlined;

  const DuoButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.color = GsColors.green,
    this.edgeColor = GsColors.greenDark,
    this.textColor = Colors.white,
    this.outlined = false,
  });

  const DuoButton.blue({
    super.key,
    required this.label,
    required this.onPressed,
  })  : color = GsColors.blue,
        edgeColor = GsColors.blueDark,
        textColor = Colors.white,
        outlined = false;

  const DuoButton.ghost({
    super.key,
    required this.label,
    required this.onPressed,
  })  : color = Colors.white,
        edgeColor = GsColors.line,
        textColor = GsColors.blue,
        outlined = true;

  @override
  State<DuoButton> createState() => _DuoButtonState();
}

class _DuoButtonState extends State<DuoButton> {
  bool _pressed = false;

  @override
  Widget build(BuildContext context) {
    final disabled = widget.onPressed == null;
    return GestureDetector(
      onTapDown: disabled ? null : (_) => setState(() => _pressed = true),
      onTapCancel: () => setState(() => _pressed = false),
      onTapUp: disabled
          ? null
          : (_) {
              setState(() => _pressed = false);
              widget.onPressed?.call();
            },
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 80),
        height: 52,
        margin: EdgeInsets.only(top: _pressed ? 4 : 0),
        decoration: BoxDecoration(
          color: disabled ? GsColors.line : widget.color,
          borderRadius: BorderRadius.circular(16),
          border: widget.outlined
              ? Border.all(color: GsColors.line, width: 2)
              : null,
          boxShadow: _pressed || disabled
              ? []
              : [
                  BoxShadow(
                    color: widget.edgeColor,
                    offset: const Offset(0, 4),
                  ),
                ],
        ),
        alignment: Alignment.center,
        child: Text(
          widget.label.toUpperCase(),
          style: Theme.of(context).textTheme.labelLarge!.copyWith(
                color: disabled ? GsColors.inkSoft : widget.textColor,
              ),
        ),
      ),
    );
  }
}
