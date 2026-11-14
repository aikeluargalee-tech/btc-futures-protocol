import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../../../../config/ad_config.dart';
import '../../../core/theme.dart';

/// Collapsible Protocol Briefing Video card bundling vGUZF.mp4.
class ProtocolVideoCard extends StatefulWidget {
  const ProtocolVideoCard({
    super.key,
    required this.expanded,
    required this.onToggleExpanded,
    this.enablePlatformPlugins = true,
  });

  final bool expanded;
  final VoidCallback onToggleExpanded;
  final bool enablePlatformPlugins;

  @override
  State<ProtocolVideoCard> createState() => _ProtocolVideoCardState();
}

class _ProtocolVideoCardState extends State<ProtocolVideoCard> {
  VideoPlayerController? _controller;
  bool _initialized = false;
  bool _muted = false;
  String? _loadError;

  @override
  void didUpdateWidget(covariant ProtocolVideoCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.expanded && !oldWidget.expanded) {
      _ensureController();
    } else if (!widget.expanded && oldWidget.expanded && _controller != null) {
      _controller!.pause();
    }
  }

  @override
  void initState() {
    super.initState();
    if (widget.expanded) {
      _ensureController();
    }
  }

  Future<void> _ensureController() async {
    if (!widget.enablePlatformPlugins || _controller != null) return;
    try {
      final ctrl = VideoPlayerController.asset(AppConfig.briefingVideoAsset);
      _controller = ctrl;
      await ctrl.initialize();
      await ctrl.setLooping(true);
      if (!mounted) return;
      ctrl.addListener(_onPlayerTick);
      setState(() => _initialized = true);
    } catch (e) {
      if (!mounted) return;
      setState(() => _loadError = 'Video unavailable: $e');
    }
  }

  void _onPlayerTick() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _controller?.removeListener(_onPlayerTick);
    _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Column(
        children: [
          InkWell(
            onTap: widget.onToggleExpanded,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
              child: Row(
                children: [
                  const Icon(
                    Icons.play_arrow_sharp,
                    color: TerminalColors.accent,
                    size: 16,
                  ),
                  const SizedBox(width: 6),
                  const Expanded(
                    child: Text(
                      'PROTOCOL BRIEFING VIDEO (vGUZF.mp4)',
                      style: TextStyle(
                        fontSize: 10.5,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0.4,
                        color: TerminalColors.text,
                      ),
                    ),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: TerminalColors.panelAlt,
                      border: Border.all(color: TerminalColors.borderDark),
                    ),
                    child: Text(
                      widget.expanded ? 'HIDE' : 'TAP TO PLAY',
                      style: const TextStyle(
                        fontSize: 9.5,
                        fontWeight: FontWeight.w700,
                        color: TerminalColors.accent,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          if (widget.expanded)
            Padding(
              padding: const EdgeInsets.fromLTRB(10, 0, 10, 10),
              child: _buildVideoBody(),
            ),
        ],
      ),
    );
  }

  Widget _buildVideoBody() {
    if (!widget.enablePlatformPlugins) {
      return Container(
        height: 140,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: TerminalColors.panelAlt,
          border: Border.all(color: TerminalColors.borderDark),
        ),
        child: const Text(
          'Video Briefing Player Ready (vGUZF.mp4)',
          style: TextStyle(color: TerminalColors.text, fontSize: 10.5),
        ),
      );
    }

    if (_loadError != null) {
      return Text(
        _loadError!,
        style: const TextStyle(color: TerminalColors.down, fontSize: 10.5),
      );
    }

    final ctrl = _controller;
    if (ctrl == null || !_initialized) {
      return Container(
        height: 160,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: TerminalColors.panelAlt,
          border: Border.all(color: TerminalColors.border),
        ),
        child: const CircularProgressIndicator(strokeWidth: 2),
      );
    }

    return Column(
      children: [
        Container(
          decoration: BoxDecoration(
            border: Border.all(color: TerminalColors.borderDark),
          ),
          child: AspectRatio(
            aspectRatio: ctrl.value.aspectRatio > 0 ? ctrl.value.aspectRatio : 16 / 9,
            child: VideoPlayer(ctrl),
          ),
        ),
        const SizedBox(height: 6),
        VideoProgressIndicator(
          ctrl,
          allowScrubbing: true,
          colors: const VideoProgressColors(
            playedColor: TerminalColors.accent,
            bufferedColor: TerminalColors.border,
            backgroundColor: TerminalColors.panelAlt,
          ),
        ),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            IconButton(
              icon: Icon(
                ctrl.value.isPlaying ? Icons.pause_rounded : Icons.play_arrow_rounded,
                color: TerminalColors.accent,
              ),
              onPressed: () {
                ctrl.value.isPlaying ? ctrl.pause() : ctrl.play();
              },
            ),
            IconButton(
              icon: Icon(
                _muted ? Icons.volume_off_rounded : Icons.volume_up_rounded,
                color: TerminalColors.muted,
              ),
              onPressed: () {
                _muted = !_muted;
                ctrl.setVolume(_muted ? 0.0 : 1.0);
                setState(() {});
              },
            ),
          ],
        ),
      ],
    );
  }
}
