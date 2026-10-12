extends SceneTree
## Makes the HD clean fonts' signed distance fields once (tron/rom_text_hd.gd: every font of CLEAN with a file,
## its letters and its wide copy for the outlines, every printable ASCII character) and saves them where
## rom_text_hd.gd looks for them (baked_path()); fields already there are kept, older ones removed. Run by
## scripts/setup.py after the Godot import:
##     godot --headless --path game -s res://tools/bake_fonts.gd
## A character outside the baked ones is still made when it is first drawn.

const RomTextHd := preload("res://tron/rom_text_hd.gd")


func _init() -> void:
	DirAccess.make_dir_recursive_absolute(RomTextHd.BAKED_DIR)
	var ts := TextServerManager.get_primary_interface()
	var keep := {}
	for name in RomTextHd.CLEAN:
		var spec: Array = RomTextHd.CLEAN[name]
		var path: String = RomTextHd.CLEAN_DIR + spec[0]
		if spec[0] == "" or not FileAccess.file_exists(path):
			continue
		for px_range in [RomTextHd.TEXT_RANGE, RomTextHd.WIDE_RANGE]:
			var out := RomTextHd.baked_path(path, px_range, spec[1])
			keep[out.get_file()] = true
			if FileAccess.file_exists(out):
				continue
			var t := Time.get_ticks_msec()
			var base := FontFile.new()
			if base.load_dynamic_font(path) != OK:
				push_warning("bake_fonts: cannot load %s" % path)
				continue
			var f := RomTextHd.msdf_copy(base, px_range)
			# the glyphs are made through the weighted font as the game draws them; they land in f's cache
			for rid in RomTextHd.weighted(f, spec[1]).get_rids():
				for c in range(32, 127):
					var glyph := ts.font_get_glyph_index(rid, RomTextHd.MSDF_SIZE, c, 0)
					if glyph:
						ts.font_render_glyph(rid, Vector2i(RomTextHd.MSDF_SIZE, 0), glyph)
			if ResourceSaver.save(f, out, ResourceSaver.FLAG_COMPRESS) != OK:
				push_warning("bake_fonts: cannot save %s" % out)
				continue
			print("bake_fonts: %s (%s, range %d) in %.1f s" % [out, name, px_range, (Time.get_ticks_msec() - t) / 1000.0])
	for file in DirAccess.get_files_at(RomTextHd.BAKED_DIR):
		if not keep.has(file):
			DirAccess.remove_absolute(RomTextHd.BAKED_DIR + file)
	quit()
