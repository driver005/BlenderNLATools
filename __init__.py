bl_info = {
    "name": "Merge NLA Strips",
    "author": "Likkez (updated by ChatGPT)",
    "version": (1, 3),
    "blender": (3, 3, 0),
    "description": "Merge multiple NLA strips into one. (Option C: skip strips with no fcurves)",
    "category": "Animation",
}

import bpy
import math


class CO_OT_CaN_MergeStrips(bpy.types.Operator):
    bl_description = "Merge multiple selected NLA strips into one (skip strips without fcurves)."
    bl_idname = 'nla_tools.nla_merge_strips'
    bl_label = "Merge NLA Strips"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # Only enable when multiple NLA strips are selected
        return getattr(context, "selected_nla_strips", None) and len(context.selected_nla_strips) > 1

    def execute(self, context):
        scene = context.scene
        wm = context.window_manager
        begin_frame = scene.frame_current

        # Find object owning the selected strips (assume same object for all selected strips)
        sel_strips_all = list(context.selected_nla_strips)
        if not sel_strips_all:
            self.report({'WARNING'}, "No selected NLA strips found.")
            return {'CANCELLED'}

        obj = sel_strips_all[0].id_data

        if not obj.animation_data:
            self.report({'WARNING'}, "Object has no animation data.")
            return {'CANCELLED'}

        # Filter selected_strips: Only keep strips that have an action with >0 fcurves
        selected_strips = []
        for s in sel_strips_all:
            a = getattr(s, "action", None)
            if a and getattr(a, "fcurves", None) and len(a.fcurves) > 0:
                selected_strips.append(s)
            else:
                print(f"Skipping strip '{s.name}' — no action or no fcurves.")

        if len(selected_strips) < 2:
            self.report({'WARNING'}, "Need at least two selected strips with fcurves to merge (others skipped).")
            return {'CANCELLED'}

        # Compute global start / end & strip mode & tracks involved
        strip_mode = 'COMBINE'
        strip_start = math.inf
        strip_end = -math.inf
        disabled_tracks = set()
        track_min_idx = math.inf

        for i, track in enumerate(obj.animation_data.nla_tracks):
            found = False
            for strip in track.strips:
                if strip in selected_strips:
                    found = True
                    disabled_tracks.add(track)
                    strip_start = min(strip_start, math.floor(strip.frame_start))
                    strip_end = max(strip_end, math.ceil(strip.frame_end))
                    # Keep 'REPLACE' precedence if any strip is REPLACE
                    if strip.blend_type == 'REPLACE' or strip_mode != 'REPLACE':
                        strip_mode = strip.blend_type
            if found:
                track_min_idx = min(track_min_idx, i)

        if strip_start == math.inf or strip_end == -math.inf:
            self.report({'ERROR'}, "Couldn't determine strip time range.")
            return {'CANCELLED'}

        # Save original mute states so we can restore later
        original_mute = {t: t.mute for t in obj.animation_data.nla_tracks}

        # Mute interfering tracks (but remember original state)
        for i, track in enumerate(obj.animation_data.nla_tracks):
            if (not track.mute) and (track not in disabled_tracks):
                # If REPLACE mode: don't mute tracks that are before the minimum track index
                if (strip_mode == 'REPLACE') and (i < track_min_idx):
                    continue
                track.mute = True
                disabled_tracks.add(track)

        # Progress bar setup
        wm.progress_begin(0, 100)
        prog = 0
        total_steps = max(1, int((strip_end - strip_start) * 2))
        def step():
            nonlocal prog
            prog += 100.0 / total_steps
            wm.progress_update(min(100, math.ceil(prog)))

        # Collect unique affected fcurves across selected strips as (data_path, array_index)
        affected = set()
        for strip in selected_strips:
            action = strip.action
            if not action:
                continue
            for fc in action.fcurves:
                affected.add((fc.data_path, fc.array_index))
        affected = sorted(affected, key=lambda x: (x[0], x[1]))  # deterministic order

        if not affected:
            # This should not happen since we filtered strips with no fcurves, but guard anyway
            self.report({'ERROR'}, "No fcurves found to bake after filtering.")
            # Restore original mute states
            for t, m in original_mute.items():
                t.mute = m
            wm.progress_end()
            return {'CANCELLED'}

        # Bake: sample values per frame for each (path, index)
        fcurve_values = []  # list of tuples (frame, [values in same order as affected])
        for frame in range(int(strip_start), int(strip_end)):
            scene.frame_set(frame)
            step()
            vals = []
            for path, idx in affected:
                try:
                    resolved = obj.path_resolve(path)
                except Exception as e:
                    # If resolution fails, append None and continue
                    print(f"Warning: path_resolve failed for '{path}': {e}")
                    vals.append(None)
                    continue

                # If the resolved value is sequence-like, try to index it
                try:
                    # Some RNA properties return floats or arrays
                    val = resolved[idx]
                except Exception:
                    # If not indexable, take the value itself
                    val = resolved
                vals.append(val)
            fcurve_values.append((frame, vals))

        # Create the merged action (create BEFORE creating the NLA strip)
        merged_name = f"{selected_strips[0].name}_merged"
        merged_action = bpy.data.actions.new(name=merged_name)

        # For each affected (path, index), create fcurve in merged_action
        new_fcurves = {}
        for (path, idx) in affected:
            try:
                fc = merged_action.fcurves.new(data_path=path, index=idx)
                # Keep linear extrapolation to be predictable
                try:
                    fc.extrapolation = 'LINEAR'
                except Exception:
                    pass
                new_fcurves[(path, idx)] = fc
            except Exception as e:
                print(f"Failed to create fcurve for {path}[{idx}]: {e}")

        # Insert keyframes for each created fcurve using sampled values
        for frame, vals in fcurve_values:
            step()
            for i, (path, idx) in enumerate(affected):
                fc = new_fcurves.get((path, idx))
                if not fc:
                    continue
                val = vals[i]
                # Skip None values where resolution failed
                if val is None:
                    continue
                # Insert keyframe
                try:
                    kp = fc.keyframe_points.insert(frame, float(val), options={'FAST'})
                    kp.interpolation = 'LINEAR'
                except Exception as e:
                    # If insertion fails, print and continue
                    print(f"Failed to insert keyframe {path}[{idx}] @ {frame}: {e}")

        # Restore/mute NLA state: mark original selected strips as muted so the merged strip drives
        prev_track = None
        for track in obj.animation_data.nla_tracks:
            # restore tracks that we added to disabled (set earlier) to their original mute state first,
            # we'll then decide which ones should be muted for merging display
            if track in original_mute:
                track.mute = original_mute[track]

            # Identify the track that contains a selected strip to put new track after (logical)
            for strip in track.strips:
                if strip in selected_strips:
                    # mute original strips so the new merged strip takes effect visually
                    strip.mute = True
                    prev_track = track

        # Create a new NLA track (no prev argument — prev= is deprecated)
        new_track = obj.animation_data.nla_tracks.new()
        new_track.name = merged_action.name

        # Create the merged strip and assign the action explicitly
        new_strip = new_track.strips.new(name=merged_name, start=strip_start, action=merged_action)
        new_strip.action = merged_action
        try:
            new_strip.blend_type = strip_mode
        except Exception:
            pass

        # Final cleanup: restore exactly the original mute states for tracks not involved,
        # but keep original selected strips muted (so merged strip shows)
        for t, m in original_mute.items():
            # Do not unmute the original selected strips' tracks if they originally were muted? Keep original state.
            t.mute = m

        # But ensure selected strips are muted so the merged strip is active
        for track in obj.animation_data.nla_tracks:
            for strip in track.strips:
                if strip in selected_strips:
                    strip.mute = True

        # End progress
        wm.progress_end()
        scene.frame_set(begin_frame)

        self.report({'INFO'}, f"Merged {len(selected_strips)} strips → '{merged_name}'")
        return {'FINISHED'}


def MergeStrips_ContextMenu(self, context):
    layout = self.layout
    layout.operator(CO_OT_CaN_MergeStrips.bl_idname)


classes = (CO_OT_CaN_MergeStrips,)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.NLA_MT_context_menu.append(MergeStrips_ContextMenu)


def unregister():
    bpy.types.NLA_MT_context_menu.remove(MergeStrips_ContextMenu)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
