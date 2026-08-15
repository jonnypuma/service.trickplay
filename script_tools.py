"""Install Pillow and generator ffmpeg/dovi_tool from settings."""

from __future__ import annotations

import xbmcgui

from script_common import _ADDON, _log
from generator_settings import GeneratorSettings, read_generator_settings
from hdr_ffmpeg_installer import (
    generator_install_tools_needed,
    install_tools_needed,
    prompt_and_install_generator_tools,
)
from pillow_installer import prompt_and_install_pillow, should_offer_pillow_download


def _install_tools_strings(settings: GeneratorSettings) -> dict[str, str]:
    return {
        "title": _ADDON.getLocalizedString(32131),
        "pillow_prompt_yes": _ADDON.getLocalizedString(32149),
        "pillow_progress_title": _ADDON.getLocalizedString(32150),
        "pillow_unsupported_message": _ADDON.getLocalizedString(32151),
        "pillow_failed_message": _ADDON.getLocalizedString(32152),
        "pillow_success_message": _ADDON.getLocalizedString(32153),
        "base_ffmpeg_prompt_yes": _ADDON.getLocalizedString(32125),
        "hdr_ffmpeg_prompt_yes": _ADDON.getLocalizedString(32099),
        "dovi_prompt_yes": _ADDON.getLocalizedString(32106),
        "prompt_no": _ADDON.getLocalizedString(32100),
        "download_yes": _ADDON.getLocalizedString(32105),
        "base_ffmpeg_progress_title": _ADDON.getLocalizedString(32126),
        "hdr_ffmpeg_progress_title": _ADDON.getLocalizedString(32101),
        "dovi_progress_title": _ADDON.getLocalizedString(32107),
        "ffmpeg_unsupported_message": _ADDON.getLocalizedString(32102),
        "dovi_unsupported_message": _ADDON.getLocalizedString(32108),
        "base_ffmpeg_failed_message": _ADDON.getLocalizedString(32127),
        "hdr_ffmpeg_failed_message": _ADDON.getLocalizedString(32103),
        "dovi_failed_message": _ADDON.getLocalizedString(32109),
        "base_ffmpeg_success_message": _ADDON.getLocalizedString(32128),
        "hdr_ffmpeg_success_message": _ADDON.getLocalizedString(32104),
        "dovi_success_message": _ADDON.getLocalizedString(32110),
        "vulkan_prompt_yes": _ADDON.getLocalizedString(32118),
        "vulkan_success_message": _ADDON.getLocalizedString(32119),
        "jellyfin_upgrade_prompt_yes": _ADDON.getLocalizedString(32225),
        "jellyfin_upgrade_success_message": _ADDON.getLocalizedString(32226),
        "already_installed": _ADDON.getLocalizedString(32129),
    }

def run_install_pillow_dialog() -> None:
    _log("run_install_pillow_dialog started")
    strings = _install_tools_strings(read_generator_settings())
    if not should_offer_pillow_download():
        xbmcgui.Dialog().notification(
            strings["title"],
            _ADDON.getLocalizedString(32185),
            xbmcgui.NOTIFICATION_INFO,
            4000,
        )
        return
    prompt_and_install_pillow(
        title=strings["title"],
        prompt_yes=strings["pillow_prompt_yes"],
        prompt_no=strings["prompt_no"],
        download_yes=strings["download_yes"],
        progress_title=strings["pillow_progress_title"],
        unsupported_message=strings["pillow_unsupported_message"],
        failed_message=strings["pillow_failed_message"],
        success_message=strings["pillow_success_message"],
    )
    try:
        from pillow_installer import invalidate_pillow_cache

        invalidate_pillow_cache()
    except ImportError:
        pass

def run_install_generator_tools_dialog() -> None:
    _log("run_install_generator_tools_dialog started")
    settings = read_generator_settings()
    strings = _install_tools_strings(settings)
    if not generator_install_tools_needed(
        hdr_tone_map_enabled=settings.hdr_tone_map,
        hdr_dovi_tool_fallback_enabled=settings.hdr_dovi_tool_fallback,
        custom_ffmpeg_path=settings.ffmpeg_path,
    ):
        xbmcgui.Dialog().notification(
            strings["title"],
            _ADDON.getLocalizedString(32186),
            xbmcgui.NOTIFICATION_INFO,
            4000,
        )
        return
    prompt_and_install_generator_tools(
        hdr_tone_map_enabled=settings.hdr_tone_map,
        hdr_dovi_tool_fallback_enabled=settings.hdr_dovi_tool_fallback,
        custom_ffmpeg_path=settings.ffmpeg_path,
        title=strings["title"],
        base_ffmpeg_prompt_yes=strings["base_ffmpeg_prompt_yes"],
        hdr_ffmpeg_prompt_yes=strings["hdr_ffmpeg_prompt_yes"],
        dovi_prompt_yes=strings["dovi_prompt_yes"],
        prompt_no=strings["prompt_no"],
        download_yes=strings["download_yes"],
        base_ffmpeg_progress_title=strings["base_ffmpeg_progress_title"],
        hdr_ffmpeg_progress_title=strings["hdr_ffmpeg_progress_title"],
        dovi_progress_title=strings["dovi_progress_title"],
        ffmpeg_unsupported_message=strings["ffmpeg_unsupported_message"],
        dovi_unsupported_message=strings["dovi_unsupported_message"],
        base_ffmpeg_failed_message=strings["base_ffmpeg_failed_message"],
        hdr_ffmpeg_failed_message=strings["hdr_ffmpeg_failed_message"],
        dovi_failed_message=strings["dovi_failed_message"],
        base_ffmpeg_success_message=strings["base_ffmpeg_success_message"],
        hdr_ffmpeg_success_message=strings["hdr_ffmpeg_success_message"],
        dovi_success_message=strings["dovi_success_message"],
        vulkan_prompt_yes=strings["vulkan_prompt_yes"],
        vulkan_success_message=strings["vulkan_success_message"],
        jellyfin_upgrade_prompt_yes=strings["jellyfin_upgrade_prompt_yes"],
        jellyfin_upgrade_success_message=strings["jellyfin_upgrade_success_message"],
    )
    try:
        from thumb_cropper import invalidate_playback_ffmpeg_cache

        invalidate_playback_ffmpeg_cache()
    except ImportError:
        pass

def run_install_tools_dialog(*, from_playback_prompt: bool = False) -> None:
    _log(
        "run_install_tools_dialog started "
        f"(from_playback_prompt={from_playback_prompt})"
    )
    settings = read_generator_settings()
    strings = _install_tools_strings(settings)
    include_generator = settings.enabled or settings.hdr_tone_map
    if not install_tools_needed(
        hdr_tone_map_enabled=settings.hdr_tone_map,
        hdr_dovi_tool_fallback_enabled=settings.hdr_dovi_tool_fallback,
        custom_ffmpeg_path=settings.ffmpeg_path,
        include_generator_tools=include_generator,
    ):
        _log("Install tools: nothing needed")
        if not from_playback_prompt:
            xbmcgui.Dialog().notification(
                strings["title"],
                strings["already_installed"],
                xbmcgui.NOTIFICATION_INFO,
                4000,
            )
        return

    if should_offer_pillow_download():
        prompt_and_install_pillow(
            title=strings["title"],
            prompt_yes=strings["pillow_prompt_yes"],
            prompt_no=strings["prompt_no"],
            download_yes=strings["download_yes"],
            progress_title=strings["pillow_progress_title"],
            unsupported_message=strings["pillow_unsupported_message"],
            failed_message=strings["pillow_failed_message"],
            success_message=strings["pillow_success_message"],
        )

    if include_generator and generator_install_tools_needed(
        hdr_tone_map_enabled=settings.hdr_tone_map,
        hdr_dovi_tool_fallback_enabled=settings.hdr_dovi_tool_fallback,
        custom_ffmpeg_path=settings.ffmpeg_path,
    ):
        prompt_and_install_generator_tools(
            hdr_tone_map_enabled=settings.hdr_tone_map,
            hdr_dovi_tool_fallback_enabled=settings.hdr_dovi_tool_fallback,
            custom_ffmpeg_path=settings.ffmpeg_path,
            title=strings["title"],
            base_ffmpeg_prompt_yes=strings["base_ffmpeg_prompt_yes"],
            hdr_ffmpeg_prompt_yes=strings["hdr_ffmpeg_prompt_yes"],
            dovi_prompt_yes=strings["dovi_prompt_yes"],
            prompt_no=strings["prompt_no"],
            download_yes=strings["download_yes"],
            base_ffmpeg_progress_title=strings["base_ffmpeg_progress_title"],
            hdr_ffmpeg_progress_title=strings["hdr_ffmpeg_progress_title"],
            dovi_progress_title=strings["dovi_progress_title"],
            ffmpeg_unsupported_message=strings["ffmpeg_unsupported_message"],
            dovi_unsupported_message=strings["dovi_unsupported_message"],
            base_ffmpeg_failed_message=strings["base_ffmpeg_failed_message"],
            hdr_ffmpeg_failed_message=strings["hdr_ffmpeg_failed_message"],
            dovi_failed_message=strings["dovi_failed_message"],
            base_ffmpeg_success_message=strings["base_ffmpeg_success_message"],
            hdr_ffmpeg_success_message=strings["hdr_ffmpeg_success_message"],
            dovi_success_message=strings["dovi_success_message"],
            vulkan_prompt_yes=strings["vulkan_prompt_yes"],
            vulkan_success_message=strings["vulkan_success_message"],
            jellyfin_upgrade_prompt_yes=strings["jellyfin_upgrade_prompt_yes"],
            jellyfin_upgrade_success_message=strings["jellyfin_upgrade_success_message"],
        )
    try:
        from pillow_installer import invalidate_pillow_cache
        from thumb_cropper import invalidate_playback_ffmpeg_cache

        invalidate_pillow_cache()
        invalidate_playback_ffmpeg_cache()
    except ImportError:
        pass

