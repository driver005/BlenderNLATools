bl_info = {
    "name": "Merge NLA Strips",
    "author": "Likkez (patched for Blender 5 by ChatGPT)",
    "version": (1, 1),
    "blender": (3, 3, 0),
    "description": "Merge multiple NLA strips into one.",
    "wiki_url": "",
    "category": "Animation",
}

import bpy
import math


class CO_OT_CaN_MergeStrips(bpy.types.Operator):
    bl_description = "Merge multiple NLA strips into one."
    bl_idname = 'nla_tools.nla_merge_strips'
    bl_label = "Merge NLA strips"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(self, context):
        return context.selected_nla_strips and len(context.selected_nla_strips) > 1

    def execute(self, context):
        obj = bpy.context.selected_nla_strips[0].id_data
        wm = bpy.context.window_manager

        begin_frame = context.scene.frame_current

        selected_strips = []
        strip_mode = 'COMBINE'
        strip_start = math.inf
        strip_end = -math.inf
        disabled_tracks = []
        track_min_idx = math.inf

        # Gather selected strips and calculate the overall range
        for i, track in enumerate(obj.animation_data.nla_tracks):
            found = False
            for strip in track.strips:
                if strip.select:
                    found = True
                    selected_strips.append(strip)
                    disabled_tracks.append(track)

                    strip_start = min(strip_start, math.floor(strip.frame_start))
                    strip_end = max(strip_end, math.ceil(strip.frame_end))

                    if strip.blend_type == 'REPLACE' or strip_mode != 'REPLACE':
                        strip_mode = strip.blend_type
            if found:
                track_min_idx = min(track_min_idx, i)

        # Disable tracks that would get in the way of baking.
        for i, track in enumerate(obj.animation_data.nla_tracks):
            if (not (track.mute or (track in disabled_tracks))) and \
            not ((strip_mode == 'REPLACE') and (i < track_min_idx)):
                disabled_tracks.append(track)
                track.mute = True

        # Initialize progress bar
        wm.progress_begin(0, 100)
        wm_progress_number = 0
        wm_progress_number_unclamped = 0
        progress_increment = 100 / max(1, ((strip_end - strip_start) * 2))

        def update_progress(progress_increment):
            nonlocal wm_progress_number, wm_progress_number_unclamped
            wm_progress_number_unclamped += progress_increment
            new_progress = math.ceil(wm_progress_number_unclamped)

            if wm_progress_number != new_progress:
                wm_progress_number = new_progress
                wm.progress_update(wm_progress_number)
                # print(wm_progress_number)

        # --------------------------------------------------------------------
        # Collect affected F-curves (SAFE FOR BLENDER 5.0)
        # --------------------------------------------------------------------
        affected_fcurves = []

        for strip in selected_strips:
            action = strip.action

            # Skip strips without actions
            if not action:
                print(f"Strip '{strip.name}' has no action – skipped.")
                continue

            # In Blender 5.0, some action types have no fcurves attribute
            fcurves = getattr(action, "fcurves", None)
            if not fcurves:
                print(f"Action '{action.name}' has no fcurves – skipped.")
                continue

            for fcurve in fcurves:
                if fcurve.array_index == 0 and fcurve.data_path not in affected_fcurves:
                    affected_fcurves.append(fcu_

