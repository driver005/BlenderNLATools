import bpy


class NLAMergeActions(bpy.types.Operator):
    bl_idname = "nla.merge_actions_safely"
    bl_label = "Merge Actions Safely"
    bl_description = "Merge all NLA strips into one action safely"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        obj = context.object
        if not obj or not obj.animation_data:
            self.report({"ERROR"}, "No animation data found")
            return {'CANCELLED'}

        ad = obj.animation_data

        if not ad.nla_tracks:
            self.report({"ERROR"}, "No NLA tracks found")
            return {'CANCELLED'}

        # --- Create merged action ---
        merged_action = bpy.data.actions.new(name=f"{obj.name}_MergedAction")
        merged_action.use_fake_user = True  # <<< CRITICAL FIX

        time_offset = 0.0

        # --- Merge ---
        for track in ad.nla_tracks:
            for strip in track.strips:

                action = strip.action
                if not action:
                    continue

                fcurves = getattr(action, "fcurves", [])

                if fcurves:
                    for old_fc in fcurves:
                        new_fc = merged_action.fcurves.new(
                            data_path=old_fc.data_path,
                            index=old_fc.array_index
                        )
                        for k in old_fc.keyframe_points:
                            new_fc.keyframe_points.insert(
                                k.co.x + time_offset,
                                k.co.y,
                                options={'FAST'}
                            )
                else:
                    # Action has no fcurves → still merge (keep time offset)
                    print(f"Empty action merged: {action.name}")

                time_offset += strip.frame_end - strip.frame_start

        # --- Assign merged action ---
        ad.action = merged_action

        # --- Clean NLA ---
        for tr in ad.nla_tracks:
            ad.nla_tracks.remove(tr)

        # Create one new track + strip so Action Editor shows it
        final_track = ad.nla_tracks.new()
        final_strip = final_track.strips.new(
            name="Merged",
            start=0.0,
            action=merged_action
        )

        # Set as active
        final_track.active = True
        final_strip.select = True
        context.scene.frame_current = 0

        self.report({"INFO"}, f"Merged into action '{merged_action.name}'")
        return {'FINISHED'}


def register():
    bpy.utils.register_class(NLAMergeActions)


def unregister():
    bpy.utils.unregister_class(NLAMergeActions)


if __name__ == "__main__":
    register()
