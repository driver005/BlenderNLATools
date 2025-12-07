bl_info = {
    "name": "Merge NLA Strips",
    "author": "Likkez (updated by ChatGPT)",
    "version": (1, 2),
    "blender": (3, 3, 0),
    "description": "Merge multiple NLA strips into one.",
    "category": "Animation",
}

import bpy
import math


class CO_OT_CaN_MergeStrips(bpy.types.Operator):
    bl_description = "Merge multiple NLA strips into one."
    bl_idname = 'nla_tools.nla_merge_strips'
    bl_label = "Merge NLA Strips"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(self, context):
        return context.selected_nla_strips and len(context.selected_nla_strips) > 1

    def execute(self, context):
        obj = context.selected_nla_strips[0].id_data
        wm = context.window_manager
        begin_frame = context.scene.frame_current

        selected_strips = []
        strip_mode = 'COMBINE'
        strip_start = math.inf
        strip_end = -math.inf
        disabled_tracks = []
        track_min_idx = math.inf

        # ------------------------------------------------------------
        # Collect strips and calculate boundaries
        # ------------------------------------------------------------
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

        # ------------------------------------------------------------
        # Mute tracks that interfere
        # ------------------------------------------------------------
        for i, track in enumerate(obj.animation_data.nla_tracks):
            if (not (track.mute or (track in disabled_tracks))) and \
            not ((strip_mode == 'REPLACE') and (i < track_min_idx)):
                disabled_tracks.append(track)
                track.mute = True

        # Progress bar setup
        wm.progress_begin(0, 100)
        prog = 0
        total_steps = max(1, (strip_end - strip_start) * 2)

        def step():
            nonlocal prog
            prog += 100 / total_steps
            wm.progress_update(min(100, math.ceil(prog)))

        # ------------------------------------------------------------
        # Collect UNIQUE affected fcurve paths (SAFE for Blender 5)
        # ------------------------------------------------------------
        affected_fcurves = []

        for strip in selected_strips:
            action = strip.action
            if not action:
                print(f"Strip '{strip.name}' has no action → skipped.")
                continue

            fcurves = getattr(action, "fcurves", None)
            if not fcurves:
                print(f"Action '{action.name}' has no fcurves → skipped.")
                continue

            for fc in fcurves:
                if fc.array_index == 0 and fc.data_path not in affected_fcurves:
                    affected_fcurves.append(fc.data_path)

        # ------------------------------------------------------------
        # SPECIAL CASE: No fcurves → still merge with empty action
        # ------------------------------------------------------------
        if not affected_fcurves:
            print("No F-curves detected → merging into empty action.")

            name = f"{selected_strips[0].name}_merged"
            action = bpy.data.actions.new(name=name)

            # Restore muted tracks
            prev_track = None
            for track in obj.animation_data.nla_tracks:
                if track in disabled_tracks:
                    track.mute = False
                for strip in track.strips:
                    if strip.select:
                        strip.mute = True
                        prev_track = track

            new_track = obj.animation_data.nla_tracks.new(prev=prev_track)
            new_track.name = action.name
            strip = new_track.strips.new(name=name, start=strip_start, action=action)
            strip.blend_type = strip_mode

            wm.progress_end()
            context.scene.frame_set(begin_frame)
            return {'FINISHED'}

        # ------------------------------------------------------------
        # Bake values frame by frame
        # ------------------------------------------------------------
        fcurve_values = []
        for frame in range(strip_start, strip_end):
            context.scene.frame_set(frame)
            step()

            vals = []
            for path in affected_fcurves:
                try:
                    vals.append(obj.path_resolve(path).copy())
                except:
                    vals.append(obj.path_resolve(path))
            fcurve_values.append(vals)

        # ------------------------------------------------------------
        # Create merged action
        # ------------------------------------------------------------
        name = f"{selected_strips[0].name}_merged"
        action = bpy.data.actions.new(name=name)

        def add_fcurve(path, idx):
            fc = action.fcurves.new(data_path=path, index=idx)
            fc.extrapolation = 'LINEAR'
            fc.keyframe_points.add(len(fcurve_values))
            return fc

        # ------------------------------------------------------------
        # Write keyframes
        # ------------------------------------------------------------
        for i, path in enumerate(affected_fcurves):
            try:
                count = len(fcurve_values[0][i])
            except:
                count = 1

            new_fcurves = [add_fcurve(path, k) for k in range(count)]

            for frame_i, vals in enumerate(fcurve_values):
                step()
                value = vals[i]

                for k, fc in enumerate(new_fcurves):
                    fc.keyframe_points[frame_i].co.x = frame_i + strip_start
                    fc.keyframe_points[frame_i].interpolation = 'LINEAR'
                    try:
                        fc.keyframe_points[frame_i].co.y = value[k]
                    except:
                        fc.keyframe_points[frame_i].co.y = value

        # ------------------------------------------------------------
        # Restore NLA state
        # ------------------------------------------------------------
        prev_track = None
        for track in obj.animation_data.nla_tracks:
            if track in disabled_tracks:
                track.mute = False

            for strip in track.strips:
                if strip.select:
                    strip.mute = True
                    prev_track = track

        # Create merged strip
        new_track = obj.animation_data.nla_tracks.new(prev=prev_track)
        new_track.name = action.name
        strip = new_track.strips.new(name=name, start=strip_start, action=action)
        strip.blend_type = strip_mode

        wm.progress_end()
        context.scene.frame_set(begin_frame)

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

