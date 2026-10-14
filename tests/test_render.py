from trend.render import Citations, chromatogram, line_paths


def test_line_labels_stay_inside_plot_and_apart():
    months = ["2026-04", "2026-05", "2026-06"]
    series = {"화장품": [[m, 1.0] for m in months],
              "a": [[m, 0.01] for m in months], "b": [[m, 0.02] for m in months],
              "c": [[m, 0.0] for m in months], "d": [[m, 2.0] for m in months]}
    g = line_paths(series, "화장품", 760, 250)
    ys = sorted(l["label_y"] for l in g["lines"])
    assert all(g["y0"] - 15 <= y <= g["y1"] for y in ys)
    assert all(b - a >= 15 - 1e-6 for a, b in zip(ys, ys[1:]))


def test_chromatogram_peaks_scale_with_counts_and_fit():
    g = chromatogram([{"term": "x", "n": 20}, {"term": "y", "n": 5}], 960, 280)
    hx, hy = (p for p in g["peaks"])
    assert hx["amp"] > hy["amp"]
    assert min(p["y"] for p in g["peaks"]) - 38 > 0      # label stays inside the SVG


def test_citations_number_in_first_seen_order():
    c = Citations({"a": {"title": "A"}, "b": {"title": "B"}})
    c(["b"]); c(["a", "b"])
    assert [e["title"] for e in c.entries({})] == ["B", "A"]
