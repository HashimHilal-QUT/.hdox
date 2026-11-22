using System;
using System.IO;
using System.IO.Compression;

public sealed class HDOXPreviewHandler
{
    public string ReadIndexHtml(string archivePath)
    {
        using var archive = ZipFile.OpenRead(archivePath);
        var mimetype = archive.GetEntry("mimetype");
        if (mimetype == null) throw new InvalidDataException("Missing HDOX mimetype");
        using var mimeStream = mimetype.Open();
        using var reader = new StreamReader(mimeStream);
        if (reader.ReadToEnd() != "application/vnd.hdox+zip")
            throw new InvalidDataException("Invalid HDOX mimetype");
        var entry = archive.GetEntry("index.html")
            ?? throw new InvalidDataException("Missing index.html");
        using var stream = entry.Open();
        using var htmlReader = new StreamReader(stream);
        return htmlReader.ReadToEnd();
    }
}
